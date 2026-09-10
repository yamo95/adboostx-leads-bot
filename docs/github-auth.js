'use strict';
// Device-only GitHub credential vault for the existing B219 viewer.
// PUBLIC key only. The matching non-extractable privateKey is supplied by enter().
// RSA-OAEP/SHA-256 with a separate label prevents report/vault cross-protocol use.
// No plaintext token, encryption secret, report, or private key is persisted here.
(() => {
  const SLOT = STORE + '-github-vault-v1';
  const PREF = SLOT + '-remember';
  const SCOPE = SEARCH_API + '|' + SEARCH_WORKFLOW;
  const LABEL = enc.encode(SLOT + '|' + KEY_ID + '|' + SCOPE);
  const PUBLIC_SPKI = 'MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEA1BGDRrTBd+CrmOiTfiP7jguUn0vkss7xJ871E5k2xbfscS/8oeDTU+z9m8Qr/axP6ra1QOPnYXxM7SdcO2w76mlCmzIIe+oCs2AYyi5H2RQQlZsNUyY5T1X/SqpCPpMm9m7CqGWvdZKLIPLjuqtdHaBkqfN/XaUv2/wGcMv7Hge8zdEOxvS6QegNDDOimsV2UlGsEt5JTO5BP16dwNaPoOCfjUK3sd7db3PrZm7mBLSmj9ghNvSjUUD91EQ9jfkgrrxYUuxeuHSLUKH5AHkpGBemX3/6G7b3m62Aum+mzE6CBvcmIfgpajqXCQ9XMmagVvZ9AzIYLaJxCr1Ow+6cE5gH80Inor/QLCiK6bshugbJz15Y9gtLqxAVey2gQITFOSC4CbnGqxRGEIWC4UAbvxZDY/2cAHcn/l1pG9y7RPc2c3ee2BtftSzjMpXmR5APhZ3JxUiRuW5akhiLOQxU+UGXHVtJ7F2QQ3zRVlNmYOdz/1IdhLOaixsWyaHXdw2NAgMBAAE=';
  const M = {
  "remember": "שמור הרשאת GitHub במכשיר זה (מוצפן)",
  "connect": "חיבור ושמירה",
  "sessionConnect": "חיבור לחלון בלבד",
  "disconnect": "ניתוק מהחלון",
  "forget": "מחיקת הרשאת GitHub מהמכשיר",
  "confirmForget": "למחוק את הרשאת GitHub השמורה במכשיר זה? הלידים וקובץ הגישה לא יימחקו.",
  "checking": "בודק חיבור ושומר הרשאה מוצפנת...",
  "saved": "ההרשאה נשמרה מוצפנת. בפתיחה הבאה של המערכת היא תיטען אוטומטית.",
  "restored": "הרשאת GitHub נטענה מהשמירה המוצפנת. אין צורך להדביק אותה שוב.",
  "connectedSaved": "GitHub מחובר — הרשאה שמורה מוצפנת במכשיר",
  "connectedSession": "GitHub מחובר לחלון זה בלבד",
  "storedLocked": "הרשאת GitHub שמורה מוצפנת; תיטען בפתיחת המערכת מחדש",
  "needed": "נדרש חיבור GitHub חד-פעמי במכשיר זה",
  "invalid": "הדבק הרשאת GitHub תקינה, לא את קובץ הגישה.",
  "failed": "חיבור GitHub נכשל. בדוק רשת והרשאת Actions: Read and write למאגר הקיים.",
  "expired": "GitHub דחה את ההרשאה (401). ייתכן שפג תוקפה או שבוטלה. יש לחבר הרשאה חדשה.",
  "corrupt": "לא ניתן לפענח את הרשאת GitHub השמורה. הדוחות לא נפגעו; חבר את ההרשאה מחדש.",
  "storage": "החיבור פועל בחלון זה, אבל השמירה המוצפנת נכשלה. בדוק את הרשאת האחסון בדפדפן.",
  "deleted": "הרשאת GitHub נמחקה מהמכשיר. הלידים והגישה לדוחות נשמרו.",
  "deleteFailed": "החיבור נותק, אבל מחיקת השמירה נכשלה. מחק את נתוני האתר בדפדפן.",
  "changed": "ההרשאה השמורה שונתה בחלון אחר. החיבור בחלון זה נותק.",
  "instructions": "הדבק את ההרשאה פעם אחת: Fine-grained token למאגר yamo95/adboostx-leads-bot בלבד, עם Actions: Read and write. בשמירה המוצפנת, היא תיטען אחרי פתיחת המערכת בגישה הרגילה. ההרשאה נשלחת רק ל־GitHub.",
  "notice": "שמור רק במכשיר אישי. השמירה היא לדפדפן זה בלבד. נעילה מנקה את ההרשאה מהחלון, לא את העותק המוצפן. מחיקה מהמכשיר אינה מבטלת את הטוקן בחשבון GitHub.",
  "forgetAll": "למחוק ממכשיר זה את מפתח הגישה, הרשאת GitHub וסימוני המעקב השמורים?"
};
  let revision = 0, working = false, activeRecord = null;
  const checkbox = element('input'); checkbox.type = 'checkbox'; checkbox.id = 'searchRemember';
  checkbox.checked = load(PREF, true) !== false;
  const rememberLabel = element('label', null, 'check'); rememberLabel.append(checkbox, element('span', M.remember));
  const forgetButton = element('button', M.forget, 'secondary'); forgetButton.id = 'searchForgetToken';
  const notice = element('p', M.notice, 'small');
  const feedback = element('p', '', 'small'); feedback.id = 'githubVaultStatus';
  feedback.setAttribute('role', 'status'); feedback.setAttribute('aria-live', 'polite');
  const auth = $('searchAuth'), actions = $('searchConnect').parentNode;
  auth.insertBefore(rememberLabel, actions); actions.append(forgetButton); auth.append(feedback, notice);
  const instructions = auth.querySelector('p.small');
  if (instructions) instructions.textContent = M.instructions;
  $('searchDisconnect').textContent = M.disconnect;
  T.forget = M.forgetAll;

  function message(text, error = false) { feedback.textContent = text; feedback.classList.toggle('error', error); }
  function stored() { try { return localStorage.getItem(SLOT); } catch { return null; } }
  function removeStored() {
    try { localStorage.removeItem(SLOT); return localStorage.getItem(SLOT) === null; } catch { return false; }
  }
  function validToken(token) { return typeof token === 'string' && /^[A-Za-z0-9_-]{20,256}$/.test(token); }
  function guard(version, key, epoch) { return version === revision && key === privateKey && epoch === generation && !!key; }
  function clearSession() { revision++; working = false; activeRecord = null; searchToken = ''; $('searchToken').value = ''; }
  function controls() {
    const record = stored(), connected = !!privateKey && !!searchToken;
    $('searchAuthState').textContent = working ? M.checking : connected ?
      (record && activeRecord === record ? M.connectedSaved : M.connectedSession) : record ? M.storedLocked : M.needed;
    $('searchConnect').textContent = checkbox.checked ? M.connect : M.sessionConnect;
    $('searchConnect').disabled = working || searchRunning || searchFlight || !privateKey;
    checkbox.disabled = working || searchRunning || searchFlight;
    forgetButton.disabled = !record && !searchToken;
    if (working) { $('searchStart').disabled = true; $('searchResume').disabled = true; }
  }
  const oldRender = renderSearch;
  renderSearch = function() { oldRender(); controls(); };

  async function seal(token) {
    const spki = buf(PUBLIC_SPKI);
    if (hex(await crypto.subtle.digest('SHA-256', spki)) !== KEY_ID) throw Error('VAULT_KEY');
    const pub = await crypto.subtle.importKey('spki', spki, { name: 'RSA-OAEP', hash: 'SHA-256' }, false, ['encrypt']);
    if (pub.algorithm.modulusLength !== 3072 || !validToken(token)) throw Error('VAULT_INPUT');
    const bytes = enc.encode(token);
    try {
      const ciphertext = await crypto.subtle.encrypt({ name: 'RSA-OAEP', label: LABEL }, pub, bytes);
      return JSON.stringify({ format: 1, key_id: KEY_ID, scope: SCOPE, ciphertext: b64(new Uint8Array(ciphertext)) });
    } finally { bytes.fill(0); }
  }
  async function open(raw, key) {
    if (typeof raw !== 'string' || raw.length > 4096) throw Error('VAULT_SIZE');
    const value = JSON.parse(raw);
    if (value.format !== 1 || value.key_id !== KEY_ID || value.scope !== SCOPE ||
        typeof value.ciphertext !== 'string' || !/^[A-Za-z0-9+/]{512}$/.test(value.ciphertext)) throw Error('VAULT_FORMAT');
    const bytes = new Uint8Array(await crypto.subtle.decrypt({ name: 'RSA-OAEP', label: LABEL }, key, buf(value.ciphertext)));
    try { const token = dec.decode(bytes); if (!validToken(token)) throw Error('VAULT_TOKEN'); return token; }
    finally { bytes.fill(0); }
  }
  async function persist(token, version, key, epoch) {
    const encrypted = await seal(token);
    if (!guard(version, key, epoch) || searchToken !== token || !checkbox.checked) return;
    try {
      localStorage.setItem(SLOT, encrypted);
      if (localStorage.getItem(SLOT) !== encrypted) throw Error('STORAGE');
      activeRecord = encrypted; message(M.saved);
    } catch { message(M.storage, true); }
  }
  async function restore() {
    const raw = stored(); if (!privateKey || !raw) { renderSearch(); return; }
    const version = ++revision, key = privateKey, epoch = generation;
    working = true; renderSearch();
    try {
      const token = await open(raw, key);
      if (!guard(version, key, epoch) || stored() !== raw) return;
      searchToken = token; activeRecord = raw; message(M.restored);
      // Restoring authorization never starts/resumes a scan and does not send a request.
    } catch { if (guard(version, key, epoch)) { searchToken = ''; message(M.corrupt, true); auth.open = true; } }
    finally { if (guard(version, key, epoch)) { working = false; renderSearch(); } }
  }
  const oldEnter = enter;
  enter = async function(key) {
    clearSession(); message('');
    const opening = oldEnter(key); // Sets generation/privateKey before its first await.
    await Promise.all([opening, restore()]);
  };
  const oldLock = lock;
  lock = function() { clearSession(); message(''); oldLock(); renderSearch(); };
  $('lock').onclick = lock;

  // Only an explicit 401 invalidates a saved credential. 403, 429 and offline
  // errors are not proof that a token expired; never delete it for those errors.
  const oldGithub = githubSearch;
  githubSearch = async function(path, method = 'GET', payload = null) {
    const token = searchToken, version = revision;
    try { return await oldGithub(path, method, payload); }
    catch (error) {
      if (error.message === 'GITHUB_401' && token && token === searchToken && version === revision) {
        if (activeRecord && stored() === activeRecord) removeStored();
        clearSession(); pauseSearch(M.expired); message(M.expired, true); auth.open = true; renderSearch();
      }
      throw error;
    }
  };
  connectSearch = async function() {
    if (!privateKey || working || searchRunning || searchFlight) return;
    const token = $('searchToken').value.trim(); $('searchToken').value = '';
    if (!validToken(token)) { message(M.invalid, true); return; }
    const version = ++revision, key = privateKey, epoch = generation;
    working = true; activeRecord = null; searchToken = token; message(M.checking); renderSearch();
    try {
      const workflow = await githubSearch('/actions/workflows/' + SEARCH_WORKFLOW);
      if (!guard(version, key, epoch)) return;
      if (workflow.state !== 'active') throw Error('WORKFLOW_INACTIVE');
      if (checkbox.checked) {
        // Encryption failures leave only a session token; never fall back to cleartext.
        try { await persist(token, version, key, epoch); }
        catch { if (guard(version, key, epoch)) message(M.storage, true); }
      } else { const removed = removeStored(); message(removed ? M.connectedSession : M.deleteFailed, !removed); }
    } catch { if (guard(version, key, epoch)) { searchToken = ''; message(M.failed, true); } }
    finally { if (guard(version, key, epoch)) { working = false; renderSearch(); } }
  };
  $('searchConnect').onclick = connectSearch;
  $('searchToken').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); void connectSearch(); } };
  const oldStart = startSearch;
  startSearch = async function(resume = false) { if (!working) return oldStart(resume); };
  $('searchDisconnect').onclick = () => { clearSession(); pauseSearch(); message(''); renderSearch(); };
  forgetButton.onclick = () => {
    if (!confirm(M.confirmForget)) return;
    clearSession(); pauseSearch(); const removed = removeStored();
    message(removed ? M.deleted : M.deleteFailed, !removed); renderSearch();
  };
  const oldForget = $('forget').onclick;
  $('forget').onclick = () => {
    const epoch = generation; oldForget();
    // Existing handler increments generation only after its confirmation succeeds.
    if (generation !== epoch) {
      clearSession(); const removed = removeStored();
      if (!removed) loginStatus(M.deleteFailed);
      renderSearch();
    }
  };
  checkbox.onchange = async () => {
    save(PREF, checkbox.checked);
    if (!checkbox.checked) { const removed = removeStored(); activeRecord = null; message(removed ? (searchToken ? M.connectedSession : M.needed) : M.deleteFailed, !removed); renderSearch(); return; }
    if (!searchToken || !privateKey || working) { renderSearch(); return; }
    const version = ++revision, key = privateKey, epoch = generation, token = searchToken;
    working = true; renderSearch();
    try { await persist(token, version, key, epoch); }
    catch { if (guard(version, key, epoch)) message(M.storage, true); }
    finally { if (guard(version, key, epoch)) { working = false; renderSearch(); } }
  };
  globalThis.addEventListener?.('storage', event => {
    if (event.key === SLOT || event.key === null) { clearSession(); pauseSearch(); message(M.changed); renderSearch(); }
  });
  globalThis.addEventListener?.('pagehide', () => { if (privateKey || searchToken) lock(); });
  renderSearch();
})();
