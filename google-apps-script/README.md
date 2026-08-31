# DigiLib Google Apps Script

1. Buat Google Sheet kosong, salin ID-nya, lalu isi `spreadsheetId` pada `CONFIG` di `Code.gs`.
2. Jalankan fungsi `setupLibrary()` sekali dari editor Apps Script. Fungsi ini membuat tab `Books`, `Members`, `Loans`, dan `Reservations` beserta header lengkapnya.
3. Buat folder Google Drive untuk sampul/PDF, lalu isi `driveFolderId` pada `CONFIG`. Simpan URL file pada kolom `coverUrl`/`pdfUrl`.
4. Pilih **Deploy → New deployment → Web app**, jalankan sebagai pemilik, dan beri akses sesuai kebutuhan.
5. Isi `REACT_APP_APPS_SCRIPT_URL` pada environment frontend dengan URL berakhiran `/exec`, lalu muat ulang aplikasi.
6. Action API tersedia: `catalog`, `login`, `borrow`, `return`, `reserve`, `members`, dan `loans`.

Untuk produksi, jangan menyimpan password polos seperti contoh awal ini. Gunakan hash atau Google Sign-In dan batasi akses file Drive.