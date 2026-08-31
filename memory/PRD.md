# DigiLib PRD

## Original problem
Membangun e-perpustakaan seperti digilib.unesa.ac.id/front menggunakan Google Apps Script.

## Architecture
Responsive React client sebagai portal katalog dan panel anggota/admin. Google Apps Script Web App menjadi adapter API, Google Sheets menjadi data store, dan Google Drive menjadi penyimpanan sampul/PDF.

## Implemented
- Beranda katalog dengan pencarian, topik populer, koleksi pilihan, statistik, dan CTA anggota.
- Katalog responsif dengan filter kategori, detail koleksi, status ketersediaan, dan modal peminjaman.
- Login anggota/admin demo, profil anggota, peminjaman aktif, dan panel admin katalog.
- Pengembalian peminjaman, antrean reservasi FIFO, dan adapter request Apps Script opsional.
- Template `google-apps-script/Code.gs` beserta `setupLibrary()` untuk membuat skema Sheet dan instruksi setup.

## Backlog
- P0: Deploy Apps Script, isi `REACT_APP_APPS_SCRIPT_URL`, lalu validasi role dan persistence nyata.
- P1: Tambahkan upload Drive dan edit katalog admin.
- P2: Tambahkan notifikasi email jatuh tempo dan statistik peminjaman per fakultas.