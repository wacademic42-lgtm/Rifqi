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
import asyncio
import resend
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

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

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


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=6)


class BookmarkIn(BaseModel):
    page: int = Field(ge=1, le=100000)


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
# Password reset
# ---------------------------------------------------------------------------
async def _send_reset_email(email: str, name: str, reset_link: str) -> bool:
    """Send reset email via Resend. Returns True if actually sent, False if fallback (console)."""
    if not RESEND_API_KEY:
        log.info("[PASSWORD RESET] %s -> %s", email, reset_link)
        return False
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;padding:24px;color:#10213f">
      <h2 style="color:#1e3a8a;margin:0 0 8px">DigiLib · Reset Kata Sandi</h2>
      <p>Halo {name or 'Anggota'},</p>
      <p>Kami menerima permintaan reset kata sandi untuk akun Anda. Klik tombol di bawah untuk membuat kata sandi baru. Link berlaku 1 jam.</p>
      <p style="margin:28px 0"><a href="{reset_link}" style="background:#1e3a8a;color:#fff;padding:12px 20px;border-radius:6px;text-decoration:none;font-weight:700">Reset kata sandi</a></p>
      <p style="font-size:12px;color:#718096">Jika tombol tidak berfungsi, salin URL berikut ke browser:<br><span style="color:#1e3a8a">{reset_link}</span></p>
      <hr style="border:0;border-top:1px solid #e2e8f0;margin:24px 0">
      <p style="font-size:11px;color:#98a4b5">Jika Anda tidak meminta reset, abaikan email ini. Sandi lama tetap aktif.</p>
    </div>
    """
    try:
        await asyncio.to_thread(resend.Emails.send, {
            "from": SENDER_EMAIL,
            "to": [email],
            "subject": "DigiLib — Reset Kata Sandi",
            "html": html,
        })
        return True
    except Exception as e:
        log.error("Resend send failed: %s", e)
        log.info("[PASSWORD RESET FALLBACK] %s -> %s", email, reset_link)
        return False


@api.post("/auth/forgot-password")
async def forgot_password(body: ForgotPasswordIn):
    email = body.email.lower()
    user = await db.users.find_one({"email": email})
    # Always respond ok to avoid email enumeration; only send when user exists.
    payload = {"ok": True, "message": "Jika email terdaftar, tautan reset telah dikirim."}
    if not user:
        return payload

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    await db.password_reset_tokens.insert_one({
        "token": token,
        "user_id": user["_id"],
        "email": email,
        "expires_at": expires_at,
        "used": False,
        "created_at": datetime.now(timezone.utc),
    })
    reset_link = f"{FRONTEND_URL}/?reset={token}"
    sent = await _send_reset_email(email, user.get("name", ""), reset_link)
    if not sent and not RESEND_API_KEY:
        # Dev/demo mode — return link for UI to display
        payload["dev_link"] = reset_link
        payload["message"] = "Mode demo: tautan reset ditampilkan di bawah (email belum dikonfigurasi)."
    return payload


@api.post("/auth/reset-password")
async def reset_password(body: ResetPasswordIn):
    now = datetime.now(timezone.utc)
    doc = await db.password_reset_tokens.find_one({"token": body.token})
    if not doc:
        raise HTTPException(400, "Tautan reset tidak valid")
    if doc.get("used"):
        raise HTTPException(400, "Tautan reset sudah digunakan")
    exp = doc.get("expires_at")
    if isinstance(exp, datetime) and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp and exp < now:
        raise HTTPException(400, "Tautan reset kedaluwarsa")
    await db.users.update_one({"_id": doc["user_id"]}, {"$set": {"password_hash": hash_pw(body.new_password)}})
    await db.password_reset_tokens.update_one({"_id": doc["_id"]}, {"$set": {"used": True, "used_at": now}})
    return {"ok": True, "message": "Kata sandi berhasil diperbarui. Silakan masuk kembali."}


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


@api.get("/books/{book_id}/related")
async def related_books(book_id: str, limit: int = 6, request: Request = None):
    """Return related books for the detail modal.
    Strategy (weighted, deduped):
      1) Books borrowed by users who also borrowed this book (excl. same book).
      2) Books sharing category + type.
      3) Books sharing only category.
      4) Featured fallback.
    If caller is authenticated, prefer books matching their loan history categories.
    Excludes the source book and books already actively loaned by the caller.
    """
    try:
        oid = ObjectId(book_id)
    except Exception:
        raise HTTPException(404, "Buku tidak ditemukan")
    source = await db.books.find_one({"_id": oid})
    if not source:
        raise HTTPException(404, "Buku tidak ditemukan")

    # Optional: identify caller if a valid access cookie is present (silently ignore errors)
    caller: Optional[dict] = None
    exclude_ids: set = {oid}
    if request is not None:
        token = request.cookies.get("access_token")
        if not token:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
        if token:
            try:
                payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
                if payload.get("type") == "access":
                    caller = await db.users.find_one({"_id": ObjectId(payload["sub"])})
            except Exception:
                caller = None
    if caller:
        my_loans = await db.loans.find({"user_id": caller["_id"]}, {"book_id": 1}).to_list(200)
        exclude_ids.update(l["book_id"] for l in my_loans)

    scored: dict = {}  # book_id -> {"score": int, "reason": str}

    # 1) Co-borrow signal: users who borrowed this book -> other books they borrowed
    co_users = await db.loans.find({"book_id": oid}, {"user_id": 1}).to_list(500)
    co_user_ids = list({l["user_id"] for l in co_users})
    if co_user_ids:
        co_loans = await db.loans.find(
            {"user_id": {"$in": co_user_ids}, "book_id": {"$ne": oid}},
            {"book_id": 1},
        ).to_list(2000)
        for cl in co_loans:
            bid = cl["book_id"]
            if bid in exclude_ids:
                continue
            entry = scored.setdefault(bid, {"score": 0, "reason": "Sering dipinjam bersama"})
            entry["score"] += 5

    # 2) Same category + same type
    same_ct = await db.books.find(
        {"_id": {"$nin": list(exclude_ids)}, "category": source["category"], "type": source.get("type", "Buku")},
    ).to_list(limit * 3)
    for b in same_ct:
        entry = scored.setdefault(b["_id"], {"score": 0, "reason": f"{b['category']} · {b.get('type','Buku')}"})
        entry["score"] += 3

    # 3) Same category only
    same_c = await db.books.find(
        {"_id": {"$nin": list(exclude_ids)}, "category": source["category"]},
    ).to_list(limit * 3)
    for b in same_c:
        entry = scored.setdefault(b["_id"], {"score": 0, "reason": f"Kategori {b['category']}"})
        entry["score"] += 2

    # 4) Personalized: caller loan history categories
    if caller:
        hist_cats = await db.loans.aggregate([
            {"$match": {"user_id": caller["_id"]}},
            {"$lookup": {"from": "books", "localField": "book_id", "foreignField": "_id", "as": "b"}},
            {"$unwind": "$b"},
            {"$group": {"_id": "$b.category", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 3},
        ]).to_list(3)
        top_cats = [h["_id"] for h in hist_cats]
        if top_cats:
            hist_books = await db.books.find(
                {"_id": {"$nin": list(exclude_ids)}, "category": {"$in": top_cats}},
            ).to_list(limit * 3)
            for b in hist_books:
                entry = scored.setdefault(b["_id"], {"score": 0, "reason": "Sesuai riwayat bacaan Anda"})
                entry["score"] += 4
                if entry["reason"] not in ("Sering dipinjam bersama",):
                    entry["reason"] = "Sesuai riwayat bacaan Anda"

    # 5) Featured fallback
    if len(scored) < limit:
        featured = await db.books.find(
            {"_id": {"$nin": list(exclude_ids)}, "featured": True},
        ).to_list(limit)
        for b in featured:
            scored.setdefault(b["_id"], {"score": 0, "reason": "Pilihan pustakawan"})
            scored[b["_id"]]["score"] += 1

    if not scored:
        return []

    # Fetch selected book docs & attach reason
    ranked = sorted(scored.items(), key=lambda kv: -kv[1]["score"])[:limit]
    ids = [bid for bid, _ in ranked]
    docs = {b["_id"]: b for b in await db.books.find({"_id": {"$in": ids}}).to_list(limit)}
    out = []
    for bid, meta in ranked:
        b = docs.get(bid)
        if not b:
            continue
        item = serialize_book(b)
        item["reason"] = meta["reason"]
        out.append(item)
    return out


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
# Bookmarks (last-read page per user+book)
# ---------------------------------------------------------------------------
@api.get("/bookmarks/{book_id}")
async def get_bookmark(book_id: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(book_id)
    except Exception:
        raise HTTPException(404, "Buku tidak ditemukan")
    doc = await db.bookmarks.find_one({"user_id": user["_id"], "book_id": oid})
    return {"page": doc.get("page", 1) if doc else 1, "updated_at": doc.get("updated_at").isoformat() if doc and doc.get("updated_at") else None}


@api.put("/bookmarks/{book_id}")
async def set_bookmark(book_id: str, body: BookmarkIn, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(book_id)
    except Exception:
        raise HTTPException(404, "Buku tidak ditemukan")
    now = datetime.now(timezone.utc)
    await db.bookmarks.update_one(
        {"user_id": user["_id"], "book_id": oid},
        {"$set": {"page": body.page, "updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {"ok": True, "page": body.page}


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
    allow_origin_regex=".*",
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
    {"title": "Analisis Data dengan Python", "author": "Fajar Nugroho", "type": "E-Book", "category": "Teknologi", "year": "2024", "stock": 10, "cover_url": "https://images.unsplash.com/photo-1526379095098-d400fd0bf935?auto=format&fit=crop&w=800&q=85", "pdf_url": "https://pdfobject.com/pdf/sample.pdf", "featured": True, "description": "Praktik langsung menganalisis data menggunakan pustaka Python populer."},
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
    await db.password_reset_tokens.create_index("token", unique=True)
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.bookmarks.create_index([("user_id", 1), ("book_id", 1)], unique=True)

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
        docs = [{**b, "created_at": datetime.now(timezone.utc), "pdf_url": b.get("pdf_url", ""), "description": b.get("description", "")} for b in SEED_BOOKS]
        await db.books.insert_many(docs)
        log.info("Seeded %d books", len(docs))

    # Idempotent: ensure the "Analisis Data dengan Python" e-book has an iframe-friendly demo PDF
    NEW_PDF = "https://pdfobject.com/pdf/sample.pdf"
    OLD_PDFS = [
        "",
        None,
        "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
        "https://africau.edu/images/default/sample.pdf",
    ]
    await db.books.update_one(
        {"title": "Analisis Data dengan Python", "$or": [{"pdf_url": {"$in": OLD_PDFS}}, {"pdf_url": {"$exists": False}}]},
        {"$set": {"pdf_url": NEW_PDF}},
    )


@app.on_event("startup")
async def on_startup():
    await seed_data()


@app.on_event("shutdown")
async def on_shutdown():
    client.close()
