"""DigiLib backend — FastAPI + MongoDB + JWT auth + Cloudinary uploads."""
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import time
import uuid
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Literal

import bcrypt
import jwt
import cloudinary
import cloudinary.utils
from bson import ObjectId
from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from motor.motor_asyncio import AsyncIOMotorClient


# ---------------------------------------------------------------------------
# Config & connections
# ---------------------------------------------------------------------------
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
JWT_ALGO = "HS256"
ACCESS_TTL_MIN = 60 * 24  # 1 day
REFRESH_TTL_DAYS = 7

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME") or None,
    api_key=os.environ.get("CLOUDINARY_API_KEY") or None,
    api_secret=os.environ.get("CLOUDINARY_API_SECRET") or None,
    secure=True,
)

app = FastAPI(title="DigiLib API")
api = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("digilib")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_pw(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def make_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TTL_MIN),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def make_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=REFRESH_TTL_DAYS),
        "type": "refresh",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    response.set_cookie(
        "access_token", access, httponly=True, secure=True, samesite="none",
        max_age=ACCESS_TTL_MIN * 60, path="/",
    )
    response.set_cookie(
        "refresh_token", refresh, httponly=True, secure=True, samesite="none",
        max_age=REFRESH_TTL_DAYS * 86400, path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")


def serialize_user(u: dict) -> dict:
    return {
        "id": str(u["_id"]),
        "email": u["email"],
        "name": u.get("name", ""),
        "role": u.get("role", "member"),
        "member_id": u.get("member_id"),
        "faculty": u.get("faculty"),
        "joined_at": u.get("joined_at").isoformat() if u.get("joined_at") else None,
    }


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(401, "Belum login")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        if payload.get("type") != "access":
            raise HTTPException(401, "Token invalid")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(401, "User tidak ditemukan")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token kedaluwarsa")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Token invalid")


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Hanya admin")
    return user


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class RegisterIn(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=6)
    faculty: Optional[str] = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class BookIn(BaseModel):
    title: str
    author: str
    type: Literal["Buku", "E-Book", "Skripsi", "Jurnal", "Tesis", "Disertasi"] = "Buku"
    category: str
    year: str
    stock: int = 1
    cover_url: Optional[str] = None
    pdf_url: Optional[str] = None
    description: Optional[str] = None
    featured: bool = False


class BookUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: Optional[str] = None
    author: Optional[str] = None
    type: Optional[str] = None
    category: Optional[str] = None
    year: Optional[str] = None
    stock: Optional[int] = None
    cover_url: Optional[str] = None
    pdf_url: Optional[str] = None
    description: Optional[str] = None
    featured: Optional[bool] = None


class MemberUpdate(BaseModel):
    name: Optional[str] = None
    faculty: Optional[str] = None
    role: Optional[Literal["admin", "member"]] = None


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------
@api.post("/auth/register")
async def register(body: RegisterIn, response: Response):
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email sudah terdaftar")
    member_id = f"DL-{secrets.token_hex(3).upper()}"
    doc = {
        "email": email,
        "name": body.name,
        "password_hash": hash_pw(body.password),
        "role": "member",
        "faculty": body.faculty or "",
        "member_id": member_id,
        "joined_at": datetime.now(timezone.utc),
    }
    result = await db.users.insert_one(doc)
    doc["_id"] = result.inserted_id
    access = make_access_token(str(result.inserted_id), email, "member")
    refresh = make_refresh_token(str(result.inserted_id))
    set_auth_cookies(response, access, refresh)
    return {"user": serialize_user(doc), "access_token": access}


@api.post("/auth/login")
async def login(body: LoginIn, response: Response):
    email = body.email.lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_pw(body.password, user.get("password_hash", "")):
        raise HTTPException(401, "Email atau kata sandi salah")
    access = make_access_token(str(user["_id"]), email, user.get("role", "member"))
    refresh = make_refresh_token(str(user["_id"]))
    set_auth_cookies(response, access, refresh)
    return {"user": serialize_user(user), "access_token": access}


@api.post("/auth/logout")
async def logout(response: Response):
    clear_auth_cookies(response)
    return {"ok": True}


@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return serialize_user(user)


@api.post("/auth/refresh")
async def refresh_token(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(401, "Refresh token missing")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        if payload.get("type") != "refresh":
            raise HTTPException(401, "Bukan refresh token")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(401, "User tidak ditemukan")
        access = make_access_token(str(user["_id"]), user["email"], user.get("role", "member"))
        response.set_cookie(
            "access_token", access, httponly=True, secure=True, samesite="none",
            max_age=ACCESS_TTL_MIN * 60, path="/",
        )
        return {"access_token": access}
    except jwt.PyJWTError:
        raise HTTPException(401, "Refresh token invalid")


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------
def serialize_book(b: dict) -> dict:
    return {
        "id": str(b["_id"]),
        "title": b["title"],
        "author": b["author"],
        "type": b.get("type", "Buku"),
        "category": b["category"],
        "year": b.get("year", ""),
        "stock": b.get("stock", 0),
        "cover_url": b.get("cover_url", ""),
        "pdf_url": b.get("pdf_url", ""),
        "description": b.get("description", ""),
        "featured": b.get("featured", False),
        "created_at": b.get("created_at").isoformat() if b.get("created_at") else None,
    }


@api.get("/books")
async def list_books(
    q: Optional[str] = None,
    category: Optional[str] = None,
    type: Optional[str] = None,
    featured: Optional[bool] = None,
    limit: int = 100,
):
    query: dict = {}
    if q:
        query["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"author": {"$regex": q, "$options": "i"}},
        ]
    if category and category not in ("Semua", "Semua kategori"):
        query["category"] = category
    if type:
        query["type"] = type
    if featured is not None:
        query["featured"] = featured
    docs = await db.books.find(query).sort("created_at", -1).to_list(limit)
    return [serialize_book(b) for b in docs]


@api.get("/books/categories")
async def list_categories():
    cats = await db.books.distinct("category")
    return sorted(cats)


@api.get("/books/{book_id}")
async def get_book(book_id: str):
    try:
        b = await db.books.find_one({"_id": ObjectId(book_id)})
    except Exception:
        raise HTTPException(404, "Buku tidak ditemukan")
    if not b:
        raise HTTPException(404, "Buku tidak ditemukan")
    return serialize_book(b)


@api.post("/books")
async def create_book(body: BookIn, _: dict = Depends(require_admin)):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    r = await db.books.insert_one(doc)
    doc["_id"] = r.inserted_id
    return serialize_book(doc)


@api.patch("/books/{book_id}")
async def update_book(book_id: str, body: BookUpdate, _: dict = Depends(require_admin)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "Tidak ada perubahan")
    r = await db.books.update_one({"_id": ObjectId(book_id)}, {"$set": updates})
    if r.matched_count == 0:
        raise HTTPException(404, "Buku tidak ditemukan")
    doc = await db.books.find_one({"_id": ObjectId(book_id)})
    return serialize_book(doc)


@api.delete("/books/{book_id}")
async def delete_book(book_id: str, _: dict = Depends(require_admin)):
    r = await db.books.delete_one({"_id": ObjectId(book_id)})
    if r.deleted_count == 0:
        raise HTTPException(404, "Buku tidak ditemukan")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Loans & Reservations
# ---------------------------------------------------------------------------
def serialize_loan(loan: dict, book: Optional[dict] = None) -> dict:
    return {
        "id": str(loan["_id"]),
        "book_id": str(loan["book_id"]),
        "user_id": str(loan["user_id"]),
        "borrowed_at": loan["borrowed_at"].isoformat(),
        "due_at": loan["due_at"].isoformat(),
        "returned_at": loan["returned_at"].isoformat() if loan.get("returned_at") else None,
        "status": loan.get("status", "active"),
        "book": serialize_book(book) if book else None,
    }


def serialize_reservation(r: dict, book: Optional[dict] = None) -> dict:
    return {
        "id": str(r["_id"]),
        "book_id": str(r["book_id"]),
        "user_id": str(r["user_id"]),
        "requested_at": r["requested_at"].isoformat(),
        "position": r.get("position", 1),
        "status": r.get("status", "waiting"),
        "book": serialize_book(book) if book else None,
    }


@api.post("/loans/borrow/{book_id}")
async def borrow_book(book_id: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(book_id)
    except Exception:
        raise HTTPException(404, "Buku tidak ditemukan")
    book = await db.books.find_one({"_id": oid})
    if not book:
        raise HTTPException(404, "Buku tidak ditemukan")

    # Prevent double borrow
    already = await db.loans.find_one({"user_id": user["_id"], "book_id": oid, "status": "active"})
    if already:
        raise HTTPException(400, "Anda sudah meminjam buku ini")

    if book.get("stock", 0) <= 0:
        # Add to reservation queue (FIFO)
        exists = await db.reservations.find_one({"user_id": user["_id"], "book_id": oid, "status": "waiting"})
        if exists:
            raise HTTPException(400, "Anda sudah dalam antrean untuk buku ini")
        count = await db.reservations.count_documents({"book_id": oid, "status": "waiting"})
        r = await db.reservations.insert_one({
            "user_id": user["_id"],
            "book_id": oid,
            "requested_at": datetime.now(timezone.utc),
            "position": count + 1,
            "status": "waiting",
        })
        doc = await db.reservations.find_one({"_id": r.inserted_id})
        return {"type": "reservation", "reservation": serialize_reservation(doc, book)}

    now = datetime.now(timezone.utc)
    loan_doc = {
        "user_id": user["_id"],
        "book_id": oid,
        "borrowed_at": now,
        "due_at": now + timedelta(days=14),
        "returned_at": None,
        "status": "active",
    }
    r = await db.loans.insert_one(loan_doc)
    await db.books.update_one({"_id": oid}, {"$inc": {"stock": -1}})
    loan_doc["_id"] = r.inserted_id
    book = await db.books.find_one({"_id": oid})
    return {"type": "loan", "loan": serialize_loan(loan_doc, book)}


@api.post("/loans/{loan_id}/return")
async def return_loan(loan_id: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(loan_id)
    except Exception:
        raise HTTPException(404, "Peminjaman tidak ditemukan")
    loan = await db.loans.find_one({"_id": oid})
    if not loan:
        raise HTTPException(404, "Peminjaman tidak ditemukan")
    if user.get("role") != "admin" and loan["user_id"] != user["_id"]:
        raise HTTPException(403, "Bukan peminjaman Anda")
    if loan.get("status") != "active":
        raise HTTPException(400, "Peminjaman sudah dikembalikan")

    now = datetime.now(timezone.utc)
    await db.loans.update_one({"_id": oid}, {"$set": {"returned_at": now, "status": "returned"}})
    await db.books.update_one({"_id": loan["book_id"]}, {"$inc": {"stock": 1}})

    # Promote next reservation in queue (FIFO)
    next_res = await db.reservations.find_one(
        {"book_id": loan["book_id"], "status": "waiting"},
        sort=[("requested_at", 1)],
    )
    if next_res:
        await db.reservations.update_one({"_id": next_res["_id"]}, {"$set": {"status": "ready"}})
        # Reindex remaining queue
        remaining = await db.reservations.find(
            {"book_id": loan["book_id"], "status": "waiting"},
            sort=[("requested_at", 1)],
        ).to_list(1000)
        for idx, r in enumerate(remaining, start=1):
            await db.reservations.update_one({"_id": r["_id"]}, {"$set": {"position": idx}})

    return {"ok": True}


@api.get("/loans/me")
async def my_loans(user: dict = Depends(get_current_user)):
    loans = await db.loans.find({"user_id": user["_id"]}).sort("borrowed_at", -1).to_list(100)
    ids = list({l["book_id"] for l in loans})
    books = {b["_id"]: b for b in await db.books.find({"_id": {"$in": ids}}).to_list(200)}
    return [serialize_loan(l, books.get(l["book_id"])) for l in loans]


@api.get("/reservations/me")
async def my_reservations(user: dict = Depends(get_current_user)):
    rs = await db.reservations.find({"user_id": user["_id"], "status": {"$in": ["waiting", "ready"]}}).sort("requested_at", 1).to_list(100)
    ids = list({r["book_id"] for r in rs})
    books = {b["_id"]: b for b in await db.books.find({"_id": {"$in": ids}}).to_list(200)}
    return [serialize_reservation(r, books.get(r["book_id"])) for r in rs]


@api.delete("/reservations/{res_id}")
async def cancel_reservation(res_id: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(res_id)
    except Exception:
        raise HTTPException(404, "Reservasi tidak ditemukan")
    r = await db.reservations.find_one({"_id": oid})
    if not r or r["user_id"] != user["_id"]:
        raise HTTPException(404, "Reservasi tidak ditemukan")
    await db.reservations.delete_one({"_id": oid})
    # reindex
    remaining = await db.reservations.find(
        {"book_id": r["book_id"], "status": "waiting"}, sort=[("requested_at", 1)]
    ).to_list(1000)
    for idx, x in enumerate(remaining, start=1):
        await db.reservations.update_one({"_id": x["_id"]}, {"$set": {"position": idx}})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin: members & stats
# ---------------------------------------------------------------------------
@api.get("/admin/members")
async def list_members(_: dict = Depends(require_admin)):
    users = await db.users.find({}).sort("joined_at", -1).to_list(1000)
    return [serialize_user(u) for u in users]


@api.patch("/admin/members/{user_id}")
async def update_member(user_id: str, body: MemberUpdate, _: dict = Depends(require_admin)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "Tidak ada perubahan")
    r = await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": updates})
    if r.matched_count == 0:
        raise HTTPException(404, "User tidak ditemukan")
    u = await db.users.find_one({"_id": ObjectId(user_id)})
    return serialize_user(u)


@api.delete("/admin/members/{user_id}")
async def delete_member(user_id: str, admin: dict = Depends(require_admin)):
    if str(admin["_id"]) == user_id:
        raise HTTPException(400, "Tidak bisa menghapus akun sendiri")
    r = await db.users.delete_one({"_id": ObjectId(user_id)})
    if r.deleted_count == 0:
        raise HTTPException(404, "User tidak ditemukan")
    return {"ok": True}


@api.get("/admin/loans")
async def all_loans(status_f: Optional[str] = Query(None, alias="status"), _: dict = Depends(require_admin)):
    q: dict = {}
    if status_f:
        q["status"] = status_f
    loans = await db.loans.find(q).sort("borrowed_at", -1).to_list(500)
    book_ids = list({l["book_id"] for l in loans})
    user_ids = list({l["user_id"] for l in loans})
    books = {b["_id"]: b for b in await db.books.find({"_id": {"$in": book_ids}}).to_list(500)}
    users = {u["_id"]: u for u in await db.users.find({"_id": {"$in": user_ids}}).to_list(500)}
    out = []
    for l in loans:
        item = serialize_loan(l, books.get(l["book_id"]))
        u = users.get(l["user_id"])
        item["user"] = serialize_user(u) if u else None
        out.append(item)
    return out


@api.get("/admin/stats")
async def stats(_: dict = Depends(require_admin)):
    total_books = await db.books.count_documents({})
    total_members = await db.users.count_documents({"role": "member"})
    active_loans = await db.loans.count_documents({"status": "active"})
    total_loans = await db.loans.count_documents({})
    overdue = await db.loans.count_documents(
        {"status": "active", "due_at": {"$lt": datetime.now(timezone.utc)}}
    )
    reservations_waiting = await db.reservations.count_documents({"status": "waiting"})

    # Top borrowed books
    pipeline = [
        {"$match": {"status": {"$in": ["active", "returned"]}}},
        {"$group": {"_id": "$book_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    top_agg = await db.loans.aggregate(pipeline).to_list(5)
    top_books = []
    for row in top_agg:
        b = await db.books.find_one({"_id": row["_id"]})
        if b:
            top_books.append({"book": serialize_book(b), "count": row["count"]})

    # Loans per category
    cat_pipeline = [
        {"$lookup": {"from": "books", "localField": "book_id", "foreignField": "_id", "as": "book"}},
        {"$unwind": "$book"},
        {"$group": {"_id": "$book.category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    per_category = await db.loans.aggregate(cat_pipeline).to_list(20)
    per_category = [{"category": r["_id"], "count": r["count"]} for r in per_category]

    return {
        "total_books": total_books,
        "total_members": total_members,
        "active_loans": active_loans,
        "total_loans": total_loans,
        "overdue": overdue,
        "reservations_waiting": reservations_waiting,
        "top_books": top_books,
        "per_category": per_category,
    }


# ---------------------------------------------------------------------------
# Cloudinary signature (optional — only if configured)
# ---------------------------------------------------------------------------
@api.get("/cloudinary/signature")
async def cloudinary_signature(
    resource_type: Literal["image", "raw"] = "image",
    folder: str = "digilib/covers",
    _: dict = Depends(require_admin),
):
    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
    api_key = os.environ.get("CLOUDINARY_API_KEY")
    api_secret = os.environ.get("CLOUDINARY_API_SECRET")
    if not (cloud_name and api_key and api_secret):
        raise HTTPException(400, "Cloudinary belum dikonfigurasi. Isi CLOUDINARY_* di backend/.env")
    if not folder.startswith("digilib/"):
        raise HTTPException(400, "Folder harus diawali digilib/")

    timestamp = int(time.time())
    params = {"timestamp": timestamp, "folder": folder}
    signature = cloudinary.utils.api_sign_request(params, api_secret)
    return {
        "signature": signature,
        "timestamp": timestamp,
        "cloud_name": cloud_name,
        "api_key": api_key,
        "folder": folder,
        "resource_type": resource_type,
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@api.get("/health")
async def health():
    return {"status": "ok"}


@api.get("/")
async def root():
    return {"name": "DigiLib API", "version": "1.0"}


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Startup: indexes + seed
# ---------------------------------------------------------------------------
SEED_BOOKS = [
    {"title": "Pendidikan Karakter di Era Digital", "author": "Dr. Nurul Hidayati", "type": "Buku", "category": "Pendidikan", "year": "2024", "stock": 4, "cover_url": "https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?auto=format&fit=crop&w=800&q=85", "featured": True, "description": "Menyoroti pembentukan karakter mahasiswa dalam ekosistem digital yang terus berubah."},
    {"title": "Metodologi Penelitian Kualitatif", "author": "Prof. Budi Santoso", "type": "Buku", "category": "Metodologi", "year": "2023", "stock": 2, "cover_url": "https://images.unsplash.com/photo-1543002588-bfa74002ed7e?auto=format&fit=crop&w=800&q=85", "featured": True, "description": "Panduan mendalam untuk merancang penelitian kualitatif yang kokoh dan valid."},
    {"title": "Transformasi Pembelajaran Berbasis Teknologi", "author": "Rina Kartika, M.Pd.", "type": "E-Book", "category": "Teknologi", "year": "2024", "stock": 8, "cover_url": "https://images.unsplash.com/photo-1497633762265-9d179a990aa6?auto=format&fit=crop&w=800&q=85", "featured": True, "description": "Strategi implementasi teknologi untuk memperkaya pengalaman belajar."},
    {"title": "Ekologi Pesisir Jawa Timur", "author": "Ahmad Fauzi", "type": "Skripsi", "category": "Sains", "year": "2022", "stock": 1, "cover_url": "https://images.unsplash.com/photo-1532012197267-da84d127e765?auto=format&fit=crop&w=800&q=85", "description": "Studi lapangan tentang keanekaragaman hayati pesisir Jawa Timur."},
    {"title": "Literasi Informasi Mahasiswa", "author": "Dewi Anggraini", "type": "Jurnal", "category": "Literasi", "year": "2024", "stock": 6, "cover_url": "https://images.unsplash.com/photo-1521587760476-6c12a4b040da?auto=format&fit=crop&w=800&q=85", "description": "Riset tentang kompetensi literasi informasi mahasiswa Indonesia."},
    {"title": "Pengantar Ilmu Komunikasi", "author": "Yusuf Pratama", "type": "Buku", "category": "Sosial", "year": "2021", "stock": 0, "cover_url": "https://images.unsplash.com/photo-1512820790803-83ca734da794?auto=format&fit=crop&w=800&q=85", "description": "Pengantar komprehensif untuk memahami dasar-dasar komunikasi manusia."},
    {"title": "Matematika Diskrit untuk Informatika", "author": "Prof. Hendra Wijaya", "type": "Buku", "category": "Teknologi", "year": "2023", "stock": 5, "cover_url": "https://images.unsplash.com/photo-1509228468518-180dd4864904?auto=format&fit=crop&w=800&q=85", "description": "Konsep matematika diskrit dan penerapannya dalam ilmu komputer."},
    {"title": "Sejarah Kebudayaan Nusantara", "author": "Siti Maryam", "type": "Buku", "category": "Sosial", "year": "2022", "stock": 3, "cover_url": "https://images.unsplash.com/photo-1461360370896-922624d12aa1?auto=format&fit=crop&w=800&q=85", "description": "Perjalanan panjang kebudayaan Nusantara dari masa ke masa."},
    {"title": "Analisis Data dengan Python", "author": "Fajar Nugroho", "type": "E-Book", "category": "Teknologi", "year": "2024", "stock": 10, "cover_url": "https://images.unsplash.com/photo-1526379095098-d400fd0bf935?auto=format&fit=crop&w=800&q=85", "featured": True, "description": "Praktik langsung menganalisis data menggunakan pustaka Python populer."},
    {"title": "Psikologi Pendidikan Modern", "author": "Dr. Lestari Widodo", "type": "Buku", "category": "Pendidikan", "year": "2023", "stock": 4, "cover_url": "https://images.unsplash.com/photo-1491841550275-ad7854e35ca6?auto=format&fit=crop&w=800&q=85", "description": "Menghadirkan pendekatan psikologi terkini untuk konteks pendidikan."},
    {"title": "Bahasa Indonesia untuk Perguruan Tinggi", "author": "Tim Dosen UNESA", "type": "Buku", "category": "Literasi", "year": "2021", "stock": 7, "cover_url": "https://images.unsplash.com/photo-1519682337058-a94d519337bc?auto=format&fit=crop&w=800&q=85", "description": "Panduan bahasa Indonesia baku untuk mahasiswa dan peneliti."},
    {"title": "Pengaruh Gawai terhadap Prestasi", "author": "Rahmat Hidayat", "type": "Tesis", "category": "Pendidikan", "year": "2023", "stock": 1, "cover_url": "https://images.unsplash.com/photo-1481627834876-b7833e8f5570?auto=format&fit=crop&w=800&q=85", "description": "Tesis yang meneliti dampak penggunaan gawai terhadap prestasi akademik."},
    {"title": "Kimia Organik Dasar", "author": "Dr. Widya Astuti", "type": "Buku", "category": "Sains", "year": "2020", "stock": 2, "cover_url": "https://images.unsplash.com/photo-1554475900-4538d10a68d0?auto=format&fit=crop&w=800&q=85", "description": "Fondasi kimia organik untuk mahasiswa sains dan teknik."},
    {"title": "Statistika Terapan Sosial", "author": "Bagus Prakoso", "type": "Jurnal", "category": "Metodologi", "year": "2024", "stock": 5, "cover_url": "https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=800&q=85", "description": "Aplikasi statistik pada isu-isu sosial kontemporer."},
    {"title": "Manajemen Perpustakaan Digital", "author": "Nur Aisyah", "type": "Disertasi", "category": "Literasi", "year": "2023", "stock": 1, "cover_url": "https://images.unsplash.com/photo-1568667256549-094345857637?auto=format&fit=crop&w=800&q=85", "description": "Riset komprehensif pengelolaan perpustakaan digital di perguruan tinggi."},
]


async def seed_data():
    await db.users.create_index("email", unique=True)
    await db.books.create_index([("title", "text"), ("author", "text")])
    await db.loans.create_index([("user_id", 1), ("status", 1)])
    await db.reservations.create_index([("book_id", 1), ("status", 1), ("requested_at", 1)])

    # Seed admin
    admin_email = os.environ["ADMIN_EMAIL"].lower()
    admin_password = os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        await db.users.insert_one({
            "email": admin_email,
            "password_hash": hash_pw(admin_password),
            "name": "Administrator",
            "role": "admin",
            "faculty": "",
            "member_id": "DL-ADMIN",
            "joined_at": datetime.now(timezone.utc),
        })
        log.info("Seeded admin user %s", admin_email)
    else:
        if not verify_pw(admin_password, existing.get("password_hash", "")):
            await db.users.update_one({"email": admin_email}, {"$set": {"password_hash": hash_pw(admin_password)}})
            log.info("Refreshed admin password")

    # Seed demo member
    demo_email = "andi@digilib.ac.id"
    if not await db.users.find_one({"email": demo_email}):
        await db.users.insert_one({
            "email": demo_email,
            "password_hash": hash_pw("member123"),
            "name": "Andi Rachman",
            "role": "member",
            "faculty": "Fakultas Ilmu Pendidikan",
            "member_id": "DL-24081",
            "joined_at": datetime.now(timezone.utc),
        })
        log.info("Seeded demo member")

    # Seed books
    if await db.books.count_documents({}) == 0:
        docs = [{**b, "created_at": datetime.now(timezone.utc), "pdf_url": "", "description": b.get("description", "")} for b in SEED_BOOKS]
        await db.books.insert_many(docs)
        log.info("Seeded %d books", len(docs))


@app.on_event("startup")
async def on_startup():
    await seed_data()


@app.on_event("shutdown")
async def on_shutdown():
    client.close()
