# DigiLib — Perpustakaan Digital

## Original Problem Statement
Bangun e-perpustakaan seperti https://digilib.unesa.ac.id/front. User awalnya minta pakai Google Apps Script, tapi memilih beralih ke stack native Emergent (React + FastAPI + MongoDB) untuk fleksibilitas & kecepatan.

## User Choices
- Backend: FastAPI + MongoDB (native Emergent stack)
- Autentikasi: JWT custom (email + password) dengan httpOnly cookies
- Upload cover/PDF: Cloudinary (kredensial belum disetel — endpoint siap aktif)
- Reset password: Resend email + fallback dev-link untuk demo
- PDF viewer: iframe (menggunakan Google Docs Viewer wrapper untuk kompatibilitas)
- Seed data: 15 buku dummy (1 buku dengan PDF demo)
- Admin panel: Kelola buku, Kelola anggota, Statistik peminjaman, Kelola peminjaman

## Personas
- **Anggota** (mahasiswa/dosen): jelajah katalog, pinjam buku, reservasi (FIFO), baca PDF online, lihat riwayat, reset password
- **Administrator**: kelola koleksi (upload cover & PDF via Cloudinary), kelola anggota, monitor peminjaman, lihat statistik

## Core Requirements
- Katalog terbuka + pencarian + filter kategori
- Detail buku dengan modal + tombol "Baca online" untuk buku ber-PDF
- Register / login / logout dengan JWT
- Lupa kata sandi + reset password lewat email (fallback dev-link untuk demo)
- Peminjaman (14 hari) dan pengembalian
- Reservasi antrean FIFO ketika stok habis; promosi otomatis saat buku kembali
- Panel admin: CRUD buku (dengan upload cover & PDF ke Cloudinary), kelola anggota, daftar peminjaman, statistik
- Sink dengan MongoDB, siap deploy

## Implemented
### Iteration 1 (Jan 2026)
- Backend FastAPI + MongoDB: auth JWT, books CRUD, loans, reservations FIFO, admin
- Frontend React: home, catalog, profile, admin panel
- Seed: admin, demo member, 15 buku
- **Testing**: 18/18 pytest pass, 100% Playwright pass

### Iteration 3 (Jan 2026)
- **PDF viewer canggih (react-pdf 10.5)**: 
  - Zoom in/out (50–300%) dengan label persentase
  - Navigasi halaman: prev/next + input jump-to-page
  - Bookmark otomatis: halaman terakhir dibaca disimpan per user + per buku (debounced 800ms), hanya trigger setelah user navigasi (bukan on-load)
  - Tombol "Bookmark" manual dengan indikator visual (badge orange "Ditandai · hal. X") + toast konfirmasi
  - Tombol "Lanjut dari halaman X" di footer saat user sedang tidak di halaman bookmark
  - Fallback "Buka di tab baru" untuk PDF host yang tidak CORS-friendly
  - Anonim: tombol bookmark diarahkan ke login prompt (tidak crash)
- **Backend bookmark endpoints**:
  - GET/PUT `/api/bookmarks/{book_id}` — upsert, unique index `(user_id, book_id)`, validasi `page: 1..100000`
- **Testing**: 28/28 pytest pass, frontend reopen-bookmark bug fixed & re-verified

### Iteration 2 (Jan 2026)
- **Cloudinary integration**: signature endpoint (image + raw/pdf), BookEditor upload buttons, graceful fallback ke input URL manual saat keys belum disetel
- **Password reset flow**:
  - `/api/auth/forgot-password` — kirim link via Resend, fallback ke console + dev_link untuk demo
  - `/api/auth/reset-password` — verifikasi token, update password, invalidate token
  - Frontend: modal AuthModal punya 4 mode (login/register/forgot/reset)
  - Auto-detect `?reset=<token>` di URL untuk auto-open reset modal
  - Anti email-enumeration: response sama untuk email yang tidak terdaftar
  - TTL index pada `password_reset_tokens` collection
- **PDF viewer inline**: modal iframe menggunakan Google Docs Viewer wrapper (kompatibel di semua browser), dengan "Buka di tab baru" sebagai fallback
- **Testing**: 22/22 pytest pass, 100% frontend flows verified

## Test Results
- Backend pytest: 22/22 pass (`/app/backend/tests/test_digilib_api.py`)
- Frontend Playwright: 100% pass
- Latest report: `/app/test_reports/iteration_6.json`

## Credentials
- Admin: `admin@digilib.ac.id` / `admin123`
- Member: `andi@digilib.ac.id` / `member123`

## Environment Variables
- `MONGO_URL`, `DB_NAME` — MongoDB
- `JWT_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` — Auth
- `FRONTEND_URL` — untuk reset link
- `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` — upload (opsional)
- `RESEND_API_KEY`, `SENDER_EMAIL` — email reset (opsional, fallback dev_link)

## Backlog (P0/P1/P2)
- **P1**: User isi kredensial Cloudinary → aktifkan upload cover & PDF asli
- **P1**: User isi RESEND_API_KEY + verifikasi domain → email reset live
- **P2**: Notifikasi email tenggat pinjam (H-3) via Resend
- **P2**: Rate limit pada `/auth/login` dan `/auth/forgot-password`
- **P2**: Halaman detail buku (route sendiri, bukan modal) untuk SEO
- **P2**: Split `server.py` menjadi routers (`auth`, `books`, `loans`, `admin`)
- **P2**: Riwayat peminjaman → export PDF/CSV
- **P2**: Pagination pada katalog + admin list

## Architecture
```
React (App.js + lib/api.js)
    ↕  axios (withCredentials)
FastAPI /api/*  (server.py)
    ↕
MongoDB (digilib_db)
    ↘ Cloudinary (opsional, aktif jika keys diisi)
    ↘ Resend email (opsional, fallback dev_link jika belum diset)
```
