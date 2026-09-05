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


# ---------- PDF field ----------
def test_pdf_url_on_python_book():
    r = requests.get(f"{API}/books", params={"q": "Python"})
    assert r.status_code == 200
    hits = [b for b in r.json() if "Analisis Data dengan Python" in b["title"]]
    assert hits, "Expected 'Analisis Data dengan Python' book in results"
    assert hits[0].get("pdf_url"), "pdf_url should be non-empty"


# ---------- Password reset ----------
def test_forgot_password_unknown_email_no_dev_link():
    r = requests.post(f"{API}/auth/forgot-password", json={"email": "nonexistent_xyz@example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert "dev_link" not in body
    assert "Jika email terdaftar" in body.get("message", "")


def test_password_reset_full_flow():
    # 1. Request reset for existing member — expect dev_link (demo mode)
    r = requests.post(f"{API}/auth/forgot-password", json={"email": MEMBER["email"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert "dev_link" in body, f"Expected dev_link in demo mode, got: {body}"
    assert "Mode demo" in body.get("message", "")
    dev_link = body["dev_link"]
    assert "reset=" in dev_link
    token = dev_link.split("reset=")[1]

    new_pw = "newpass456"
    try:
        # 2. Reset with the token
        rr = requests.post(f"{API}/auth/reset-password", json={"token": token, "new_password": new_pw})
        assert rr.status_code == 200, rr.text
        assert rr.json().get("ok") is True

        # 3. Login with old password should fail
        old_login = requests.post(f"{API}/auth/login", json=MEMBER)
        assert old_login.status_code == 401

        # 4. Login with new password should work
        new_login = requests.post(f"{API}/auth/login", json={"email": MEMBER["email"], "password": new_pw})
        assert new_login.status_code == 200, new_login.text

        # 5. Reuse of same token -> 400 'sudah digunakan'
        reuse = requests.post(f"{API}/auth/reset-password", json={"token": token, "new_password": "another123"})
        assert reuse.status_code == 400
        assert "sudah digunakan" in reuse.json().get("detail", "")
    finally:
        # Restore original password using a fresh reset token so subsequent tests / demo still work
        r2 = requests.post(f"{API}/auth/forgot-password", json={"email": MEMBER["email"]})
        tok2 = r2.json()["dev_link"].split("reset=")[1]
        restore = requests.post(f"{API}/auth/reset-password", json={"token": tok2, "new_password": MEMBER["password"]})
        assert restore.status_code == 200, f"Failed to restore member password: {restore.text}"


def test_reset_password_invalid_token():
    r = requests.post(f"{API}/auth/reset-password", json={"token": "invalid_random_token_xyz", "new_password": "whatever1"})
    assert r.status_code == 400
    assert "tidak valid" in r.json().get("detail", "")


# ---------- Bookmarks ----------
def _python_book_id():
    r = requests.get(f"{API}/books", params={"q": "Python"})
    hits = [b for b in r.json() if "Analisis Data dengan Python" in b["title"]]
    assert hits, "Expected Python book"
    return hits[0]["id"]


def test_bookmark_requires_auth():
    bid = _python_book_id()
    r = requests.get(f"{API}/bookmarks/{bid}")
    assert r.status_code == 401
    r2 = requests.put(f"{API}/bookmarks/{bid}", json={"page": 3})
    assert r2.status_code == 401


def test_bookmark_get_before_set_returns_default(member_client):
    # use a throwaway book so there is definitely no doc yet
    # login as a NEW user to avoid conflict
    s = _session()
    email = f"bm_{uuid.uuid4().hex[:8]}@digilib.ac.id"
    reg = s.post(f"{API}/auth/register", json={"name": "BM User", "email": email, "password": "pass1234"})
    assert reg.status_code == 200
    bid = _python_book_id()
    r = s.get(f"{API}/bookmarks/{bid}")
    assert r.status_code == 200
    body = r.json()
    assert body == {"page": 1, "updated_at": None}
    s.post(f"{API}/auth/logout")


def test_bookmark_put_then_get_persists(member_client):
    bid = _python_book_id()
    r = member_client.put(f"{API}/bookmarks/{bid}", json={"page": 5})
    assert r.status_code == 200, r.text
    assert r.json()["page"] == 5
    g = member_client.get(f"{API}/bookmarks/{bid}")
    assert g.status_code == 200
    body = g.json()
    assert body["page"] == 5
    assert body["updated_at"] is not None
    # cleanup: reset to 1
    member_client.put(f"{API}/bookmarks/{bid}", json={"page": 1})


def test_bookmark_invalid_page(member_client):
    bid = _python_book_id()
    r = member_client.put(f"{API}/bookmarks/{bid}", json={"page": 0})
    assert r.status_code == 422
    r2 = member_client.put(f"{API}/bookmarks/{bid}", json={"page": -5})
    assert r2.status_code == 422


def test_bookmark_invalid_book_id(member_client):
    r = member_client.put(f"{API}/bookmarks/not_a_valid_object_id", json={"page": 2})
    assert r.status_code == 404
    r2 = member_client.get(f"{API}/bookmarks/not_a_valid_object_id")
    assert r2.status_code == 404


def test_bookmark_isolated_between_users(admin_client, member_client):
    bid = _python_book_id()
    member_client.put(f"{API}/bookmarks/{bid}", json={"page": 7})
    admin_client.put(f"{API}/bookmarks/{bid}", json={"page": 12})
    m = member_client.get(f"{API}/bookmarks/{bid}").json()
    a = admin_client.get(f"{API}/bookmarks/{bid}").json()
    assert m["page"] == 7
    assert a["page"] == 12
    # cleanup
    member_client.put(f"{API}/bookmarks/{bid}", json={"page": 1})
    admin_client.put(f"{API}/bookmarks/{bid}", json={"page": 1})


# ---------- Cloudinary signature ----------
def test_cloudinary_signature_missing_config(admin_client):
    r = admin_client.get(f"{API}/cloudinary/signature")
    assert r.status_code == 400
    assert "Cloudinary belum dikonfigurasi" in r.json().get("detail", "")


def test_cloudinary_signature_forbidden_for_member(member_client):
    r = member_client.get(f"{API}/cloudinary/signature")
    assert r.status_code == 403
