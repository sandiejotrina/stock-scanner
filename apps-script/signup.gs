/**
 * Money Trail email signups. Paste into the Apps Script editor of the "Money Trail signups" Google Sheet
 * (Extensions > Apps Script), then Deploy > New deployment > Web app, Execute as: Me, Who has access: Anyone.
 * Copy the web app URL into SIGNUP_URL at the top of site/app.js.
 *
 * Writes one row per new email: email, signed up (date), page they signed up on. Duplicates are skipped.
 */
function doPost(e) {
  var p = (e && e.parameter) || {};
  var email = String(p.email || '').trim().toLowerCase();
  var valid = /^[^\s@=+\-][^\s@]*@[^\s@]+\.[^\s@]{2,}$/.test(email) && email.length <= 254;
  if (p.website || !valid) return ContentService.createTextOutput('ignored');

  var lock = LockService.getScriptLock();
  lock.waitLock(5000);
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
    if (sheet.getLastRow() === 0) sheet.appendRow(['email', 'signed up', 'page']);
    var last = sheet.getLastRow();
    var known = last > 1 ? sheet.getRange(2, 1, last - 1, 1).getValues().map(function (r) { return r[0]; }) : [];
    if (known.indexOf(email) === -1) {
      var page = String(p.page || '').replace(/[^a-z]/g, '').slice(0, 20);
      sheet.appendRow([email, new Date(), page]);
    }
  } finally {
    lock.releaseLock();
  }
  return ContentService.createTextOutput('ok');
}
