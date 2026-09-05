"""DigiLib backend integration tests — auth, books, loans, reservations, admin, cloudinary."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://digilib-portal-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@digilib.ac.id", "password": "admin123"}
MEMBER = {"email": "andi@digilib.ac.id", "password": "member123"}


def _session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_client():
    s = _session()
    r = s.post(f"{API}/auth/login", json=ADMIN)
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module")
def member_client():
    s = _session()
    r = s.post(f"{API}/auth/login", json=MEMBER)
    assert r.status_code == 200, r.text
    return s


# ---------- Health ----------
def test_health():
    r = requests.get(f"{API}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------- Auth ----------
def test_login_wrong_password():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN["email"], "password": "wrong"})
    assert r.status_code == 401
    assert "Email atau kata sandi salah" in r.json().get("detail", "")


def test_me_without_cookie():
    r = requests.get(f"{API}/auth/me")
    assert r.status_code == 401


def test_register_and_me():
    s = _session()
    email = f"test_{uuid.uuid4().hex[:8]}@digilib.ac.id"
    r = s.post(f"{API}/auth/register", json={"name": "Test User", "email": email, "password": "pass1234", "faculty": "FT"})
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert user["email"] == email
    assert user["role"] == "member"
    # cookie set
    assert "access_token" in s.cookies
    r2 = s.get(f"{API}/auth/me")
    assert r2.status_code == 200
    assert r2.json()["email"] == email
    # cleanup: logout
    s.post(f"{API}/auth/logout")


def test_admin_login_and_role(admin_client):
    r = admin_client.get(f"{API}/auth/me")
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_logout_clears_cookies():
    s = _session()
    s.post(f"{API}/auth/login", json=MEMBER)
    assert s.cookies.get("access_token")
    r = s.post(f"{API}/auth/logout")
    assert r.status_code == 200
    # after logout, /me should be unauthorized
    s2 = requests.Session()
    r2 = s2.get(f"{API}/auth/me")
    assert r2.status_code == 401


# ---------- Books ----------
def test_list_books_15():
    r = requests.get(f"{API}/books")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 15


def test_books_filters():
    r = requests.get(f"{API}/books", params={"featured": "true"})
    assert r.status_code == 200
    for b in r.json():
        assert b["featured"] is True
    r2 = requests.get(f"{API}/books", params={"q": "Python"})
    assert r2.status_code == 200
    assert any("Python" in b["title"] for b in r2.json())
    r3 = requests.get(f"{API}/books", params={"category": "Pendidikan"})
    assert r3.status_code == 200
    for b in r3.json():
        assert b["category"] == "Pendidikan"


def test_get_book_by_id_and_404():
    r = requests.get(f"{API}/books")
    bid = r.json()[0]["id"]
    g = requests.get(f"{API}/books/{bid}")
    assert g.status_code == 200
    assert g.json()["id"] == bid
    bad = requests.get(f"{API}/books/nonexistentid")
    assert bad.status_code == 404


def test_book_crud_admin_only(admin_client, member_client):
    payload = {"title": "TEST Book", "author": "TEST Author", "type": "Buku",
               "category": "Pendidikan", "year": "2025", "stock": 3, "featured": False}
    # Member forbidden
    r_forbidden = member_client.post(f"{API}/books", json=payload)
    assert r_forbidden.status_code == 403
    # Admin creates
    r = admin_client.post(f"{API}/books", json=payload)
    assert r.status_code == 200
    bid = r.json()["id"]
    # Update
    up = admin_client.patch(f"{API}/books/{bid}", json={"stock": 7})
    assert up.status_code == 200
    assert up.json()["stock"] == 7
    # Member cannot delete
    fd = member_client.delete(f"{API}/books/{bid}")
    assert fd.status_code == 403
    # Admin deletes
    d = admin_client.delete(f"{API}/books/{bid}")
    assert d.status_code == 200


# ---------- Loans ----------
def test_loan_borrow_return_flow(member_client, admin_client):
    # Create a fresh book with stock 1
    r = admin_client.post(f"{API}/books", json={
        "title": "TEST Loan Book", "author": "T", "type": "Buku",
        "category": "Pendidikan", "year": "2025", "stock": 1
    })
    bid = r.json()["id"]
    try:
        b1 = member_client.post(f"{API}/loans/borrow/{bid}")
        assert b1.status_code == 200, b1.text
        data = b1.json()
        assert data["type"] == "loan"
        loan_id = data["loan"]["id"]
        # stock decremented
        g = requests.get(f"{API}/books/{bid}")
        assert g.json()["stock"] == 0
        # duplicate borrow -> 400 (but stock=0 now, so triggers reservation branch; test another way)
        # Return it
        ret = member_client.post(f"{API}/loans/{loan_id}/return")
        assert ret.status_code == 200
        g2 = requests.get(f"{API}/books/{bid}")
        assert g2.json()["stock"] == 1
    finally:
        admin_client.delete(f"{API}/books/{bid}")


def test_duplicate_active_borrow(member_client, admin_client):
    r = admin_client.post(f"{API}/books", json={
        "title": "TEST Dup Borrow", "author": "T", "type": "Buku",
        "category": "Pendidikan", "year": "2025", "stock": 2
    })
    bid = r.json()["id"]
    try:
        b1 = member_client.post(f"{API}/loans/borrow/{bid}")
        assert b1.status_code == 200
        loan_id = b1.json()["loan"]["id"]
        b2 = member_client.post(f"{API}/loans/borrow/{bid}")
        assert b2.status_code == 400
        member_client.post(f"{API}/loans/{loan_id}/return")
    finally:
        admin_client.delete(f"{API}/books/{bid}")


# ---------- Reservations FIFO ----------
def test_reservation_fifo_flow(member_client, admin_client):
    # Book with stock 0
    r = admin_client.post(f"{API}/books", json={
        "title": "TEST Reserve", "author": "T", "type": "Buku",
        "category": "Pendidikan", "year": "2025", "stock": 0
    })
    bid = r.json()["id"]
    try:
        # Member borrows -> reservation
        res = member_client.post(f"{API}/loans/borrow/{bid}")
        assert res.status_code == 200
        assert res.json()["type"] == "reservation"
        res_id = res.json()["reservation"]["id"]
        assert res.json()["reservation"]["position"] == 1
        # Duplicate reservation forbidden
        dup = member_client.post(f"{API}/loans/borrow/{bid}")
        assert dup.status_code == 400
        # Cancel reservation
        cancel = member_client.delete(f"{API}/reservations/{res_id}")
        assert cancel.status_code == 200
    finally:
        admin_client.delete(f"{API}/books/{bid}")


# ---------- Admin members ----------
def test_admin_members_and_self_delete_protection(admin_client):
    r = admin_client.get(f"{API}/admin/members")
    assert r.status_code == 200
    users = r.json()
    assert len(users) >= 2
    me = admin_client.get(f"{API}/auth/me").json()
    d = admin_client.delete(f"{API}/admin/members/{me['id']}")
    assert d.status_code == 400


def test_admin_member_update(admin_client):
    users = admin_client.get(f"{API}/admin/members").json()
    member = next(u for u in users if u["email"] == MEMBER["email"])
    original = member.get("faculty") or ""
    r = admin_client.patch(f"{API}/admin/members/{member['id']}", json={"faculty": "TEST-FIP"})
    assert r.status_code == 200
    assert r.json()["faculty"] == "TEST-FIP"
    # restore
    admin_client.patch(f"{API}/admin/members/{member['id']}", json={"faculty": original})


# ---------- Admin loans & stats ----------
def test_admin_loans_and_stats(admin_client):
    r = admin_client.get(f"{API}/admin/loans")
    assert r.status_code == 200
    r2 = admin_client.get(f"{API}/admin/loans", params={"status": "returned"})
    assert r2.status_code == 200
    for l in r2.json():
        assert l["status"] == "returned"
    s = admin_client.get(f"{API}/admin/stats")
    assert s.status_code == 200
    body = s.json()
    for k in ["total_books", "total_members", "active_loans", "top_books", "per_category"]:
        assert k in body


# ---------- Cloudinary signature ----------
def test_cloudinary_signature_missing_config(admin_client):
    r = admin_client.get(f"{API}/cloudinary/signature")
    assert r.status_code == 400
    assert "Cloudinary belum dikonfigurasi" in r.json().get("detail", "")


def test_cloudinary_signature_forbidden_for_member(member_client):
    r = member_client.get(f"{API}/cloudinary/signature")
    assert r.status_code == 403
