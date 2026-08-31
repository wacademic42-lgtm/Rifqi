/** DigiLib API — Google Apps Script Web App
 * Sheets: Books, Members, Loans. Drive files use public view URLs.
 * Deploy: Execute as Me, Who has access: Anyone.
 */
const CONFIG = { spreadsheetId: 'PASTE_SPREADSHEET_ID', driveFolderId: 'PASTE_DRIVE_FOLDER_ID' };

function doGet(e) { return json_(route_(e.parameter || {}, null)); }
function doPost(e) {
  const body = JSON.parse(e.postData.contents || '{}');
  return json_(route_(body, body.action));
}
function route_(params, action) {
  action = action || params.action || 'catalog';
  if (action === 'catalog') return { ok: true, data: readSheet_('Books') };
  if (action === 'login') return login_(params.email, params.password);
  if (action === 'borrow') return loan_(params, 'borrow');
  if (action === 'return') return loan_(params, 'return');
  if (action === 'members') return { ok: true, data: readSheet_('Members') };
  if (action === 'loans') return { ok: true, data: readSheet_('Loans') };
  if (action === 'addBook') return appendRow_('Books', params.book);
  return { ok: false, error: 'Unknown action' };
}
function readSheet_(name) {
  const values = SpreadsheetApp.openById(CONFIG.spreadsheetId).getSheetByName(name).getDataRange().getValues();
  const headers = values.shift();
  return values.map(row => headers.reduce((out, key, i) => { out[key] = row[i]; return out; }, {}));
}
function login_(email, password) {
  const member = readSheet_('Members').find(row => String(row.email).toLowerCase() === String(email).toLowerCase() && String(row.password) === String(password));
  if (!member) return { ok: false, error: 'Email atau kata sandi tidak sesuai' };
  return { ok: true, data: { id: member.id, name: member.name, role: member.role, email: member.email } };
}
function loan_(params, mode) {
  const sheet = SpreadsheetApp.openById(CONFIG.spreadsheetId).getSheetByName('Loans');
  sheet.appendRow([Utilities.getUuid(), params.memberId, params.bookId, new Date(), mode === 'borrow' ? 'ACTIVE' : 'RETURNED']);
  return { ok: true, message: mode === 'borrow' ? 'Buku berhasil dipinjam' : 'Buku berhasil dikembalikan' };
}
function appendRow_(name, item) { SpreadsheetApp.openById(CONFIG.spreadsheetId).getSheetByName(name).appendRow(Object.values(item)); return { ok: true }; }
function json_(data) { return ContentService.createTextOutput(JSON.stringify(data)).setMimeType(ContentService.MimeType.JSON); }

// Header row examples:
// Books: id,title,author,type,category,year,stock,coverUrl,pdfUrl
// Members: id,name,email,password,role,joinedAt
// Loans: id,memberId,bookId,borrowedAt,status