# DigiLib Google Apps Script

1. Buat Google Sheet dengan tab `Books`, `Members`, dan `Loans` menggunakan header di bagian bawah `Code.gs`.
2. Buat folder Google Drive untuk sampul/PDF, lalu isi `spreadsheetId` dan `driveFolderId` pada `CONFIG`.
3. Tempel `Code.gs` ke Apps Script, pilih **Deploy → New deployment → Web app**, jalankan sebagai pemilik, dan beri akses sesuai kebutuhan.
4. Arahkan client ke URL Web App dengan action `catalog`, `login`, `borrow`, `return`, `members`, atau `loans`.

Untuk produksi, jangan menyimpan password polos seperti contoh awal ini. Gunakan hash atau Google Sign-In dan batasi akses file Drive.