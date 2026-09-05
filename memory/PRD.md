# DigiLib — Perpustakaan Digital

## Original Problem Statement
Bangun e-perpustakaan seperti https://digilib.unesa.ac.id/front. User awalnya minta pakai Google Apps Script, tapi memilih beralih ke stack native Emergent (React + FastAPI + MongoDB) untuk fleksibilitas & kecepatan.

## User Choices
- Backend: FastAPI + MongoDB (native Emergent stack)
- Autentikasi: JWT custom (email + password) dengan httpOnly cookies
- Upload cover/PDF: Cloudinary (kredensial belum disetel — endpoint siap aktif)
- Seed data: 15 buku dummy
- Admin panel: Kelola buku, Kelola anggota, Statistik peminjaman, Kelola peminjaman

## Personas
- **Anggota** (mahasiswa/dosen): jelajah katalog, pinjam buku, reservasi (FIFO), lihat riwayat
- **Administrator**: kelola koleksi & anggota, monitor peminjaman, lihat statistik

## Core Requirements
- Katalog terbuka + pencarian + filter kategori
- Detail buku dalam modal
- Register / login / logout dengan JWT
- Peminjaman (14 hari) dan pengembalian
- Reservasi antrean FIFO ketika stok habis; promosi otomatis saat buku kembali
- Panel admin: CRUD buku, kelola anggota, daftar peminjaman, statistik
- Sink dengan MongoDB, siap deploy

## Implemented (Jan 2026)
- **Backend** (`/app/backend/server.py`)
  - Auth JWT (register/login/logout/me/refresh) dengan bcrypt + httpOnly cookies SameSite=None
  - Books: list, detail, kategori, admin CRUD
  - Loans: borrow, return, my loans; stok terhitung otomatis
  - Reservations FIFO + promosi + cancel + re-index queue
  - Admin: members list/update/delete (bukan self), semua loans dengan info user+book, stats agregat
  - Cloudinary signature endpoint (aktif otomatis saat env keys disetel)
  - Seed: admin, demo member, 15 buku
  - MongoDB indexes: users.email unique, books text index, loans compound, reservations compound
- **Frontend** (`/app/frontend/src/App.js`, `/app/frontend/src/lib/api.js`)
  - Home hero + featured + stats strip real-time
  - Katalog dengan search debounce + category filter (server-side)
  - Modal detail buku + tombol pinjam / masuk antrean
  - Auth modal ganda (login/register) dengan error handling
  - Profil: ringkasan, peminjaman aktif, riwayat, antrean reservasi (batalkan)
  - Admin panel dengan 4 tab: Katalog (CRUD), Anggota, Peminjaman, Statistik (top books + per kategori)
  - Toast notification + responsive mobile

## Test Results
- Backend pytest: 18/18 pass
- Frontend Playwright: 100% pass
- Report: `/app/test_reports/iteration_5.json`
- Test file: `/app/backend/tests/test_digilib_api.py`

## Credentials
- Admin: `admin@digilib.ac.id` / `admin123`
- Member: `andi@digilib.ac.id` / `member123`

## Backlog (P0/P1/P2)
- **P1**: Cloudinary keys dari user → upload cover & PDF asli via BookEditor
- **P1**: Riwayat peminjaman → export PDF/CSV
- **P2**: Notifikasi email tenggat via SendGrid/Resend
- **P2**: Reset password lewat email
- **P2**: Split `server.py` menjadi modul routers (`auth`, `books`, `loans`, `admin`)
- **P2**: Rate limit login (5x/15 menit)
- **P2**: Halaman baca PDF inline

## Architecture
```
Frontend (React) ↔ FastAPI (/api/*) ↔ MongoDB (digilib_db)
                                   ↘ Cloudinary (opsional)
```
