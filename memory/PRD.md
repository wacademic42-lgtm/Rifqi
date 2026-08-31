# DigiLib PRD

## Original problem
Membangun e-perpustakaan seperti digilib.unesa.ac.id/front menggunakan Google Apps Script.

## Architecture
Responsive React client sebagai portal katalog dan panel anggota/admin. Google Apps Script Web App menjadi adapter API, Google Sheets menjadi data store, dan Google Drive menjadi penyimpanan sampul/PDF.

## Implemented
- Beranda katalog dengan pencarian, topik populer, koleksi pilihan, statistik, dan CTA anggota.
- Katalog responsif dengan filter kategori, detail koleksi, status ketersediaan, dan modal peminjaman.
- Login anggota/admin demo, profil anggota, peminjaman aktif, dan panel admin katalog.
- Template `google-apps-script/Code.gs` beserta skema sheet dan instruksi setup.

## Backlog
- P0: Sambungkan URL Web App Apps Script dan validasi role di server.
- P1: Tambahkan upload Drive, pengembalian, reservasi antrean, dan edit katalog admin.
- P2: Tambahkan notifikasi email jatuh tempo dan statistik peminjaman per fakultas.