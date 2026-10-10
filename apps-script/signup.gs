/**
 * Money Trail email signups. Paste into the Apps Script editor of the "Money Trail signups" Google Sheet
 * (Extensions > Apps Script), then Deploy > New deployment > Web app, Execute as: Me, Who has access: Anyone.
 * Copy the web app URL into SIGNUP_URL at the top of site/app.js.
 *
 * Writes one row per new email: email, signed up (date), page, first name, subscribed (yes/no).
 * A repeat signup that now ticks the box updates subscribed to yes. Duplicates are otherwise skipped.
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
    if (sheet.getLastRow() === 0) sheet.appendRow(['email', 'signed up', 'page', 'first name', 'subscribed']);
    if (sheet.getRange(1, 4).getValue() === '') sheet.getRange(1, 4, 1, 2).setValues([['first name', 'subscribed']]);
    var last = sheet.getLastRow();
    var known = last > 1 ? sheet.getRange(2, 1, last - 1, 1).getValues().map(function (r) { return r[0]; }) : [];
    var page = String(p.page || '').replace(/[^a-z]/g, '').slice(0, 20);
    // Strip characters a spreadsheet could read as a formula.
    var name = String(p.first_name || '').replace(/^[=+\-@]+/, '').replace(/[<>]/g, '').trim().slice(0, 60);
    var subscribed = p.subscribe === 'yes' ? 'yes' : 'no';
    var at = known.indexOf(email);
    if (at === -1) {
      sheet.appendRow([email, new Date(), page, name, subscribed]);
    } else if (subscribed === 'yes') {
      sheet.getRange(at + 2, 5).setValue('yes');
      if (name && !sheet.getRange(at + 2, 4).getValue()) sheet.getRange(at + 2, 4).setValue(name);
    }
  } finally {
    lock.releaseLock();
  }
  return ContentService.createTextOutput('ok');
}
