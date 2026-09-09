'use strict';
// Review-layer filtering. Raw evidence remains available under All findings.
// No private keys, contact exports, or outreach are added to the public app.
function explicitCommunity(c){
  if(c.channel&&c.channel!=='telegram')return false;
  const text=String(c.evidence||'');
  if(/\b(owner|admin|manager|agent|developer)\b/i.test(text))return false;
  return /\btelegram\s+(?:support\s+)?(?:group|channel)\s*[.!]?$/i.test(text.trim());
}
const REVIEW_PURPOSE=/^(?:abuse|dmca|legal|privacy|copyright|takedown|security|noreply|no-reply|complaints?|appeals?|eudsa|dpo|gdpr|billing|press|media|bugs?|idea)(?:[._+-]|$)/i;
const REVIEW_PLACEHOLDER=/^(?:you|yourname|youremail|your-email|user|username|test|example|name)@|@(?:example\.(?:com|org|net)|domain\.com|email\.com|test\.com)$/i;
// These discovered sites are software tools, enterprise storage or institutional
// collections, not the requested core publisher profile. Keep them review-only.
const REVIEW_SCOPE=new Set(['rclone.org','raidrive.com','cyberduck.io','multcloud.com','clonr.co','dropbox.com','mega.io','pcloud.com','jumpshare.com','sweet.tv','rts.ch','jfc.org.il','cinematheque-bretagne.bzh','abandonware-magazines.org','tvgazeta.com.br','joj.sk','arcoiris.tv','retinalatina.org','rtvcplay.co','stvr.sk']);
const REVIEW_MAIL=/[A-Z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9.-]*[A-Z0-9])?\.[A-Z]{2,24}/gi;
function reviewReason(c){
  const domain=String(c.domain||'').toLowerCase().replace(/^www\./,'');
  if([...REVIEW_SCOPE].some(h=>domain===h||domain.endsWith('.'+h)))return 'ADJACENT_SITE_SCOPE';
  if(c.channel==='whatsapp' && domain==='sportzfytvs.net' && String(c.contact)==='+3167620901')return 'INCOMPLETE_PHONE';
  if(c.channel==='email'){
    const value=String(c.contact||'').toLowerCase();
    // Service-provider routes are retained for review, not publisher outreach.
    // Sources: https://guestpost.cc/contact-us/ and https://www.domain-evo.com/
    if(value.endsWith('@guestpost.cc'))return 'SEO_SERVICE_CONTACT';
    if(value.endsWith('@domain-evo.com'))return 'DOMAIN_SERVICE_CONTACT';
    if(/\.(?:example|invalid|test|localhost)$/.test(value))return 'PLACEHOLDER';
    if(domain==='pastelink.net' && value.endsWith('@stopitnow.org.uk'))return 'UNRELATED_HELP_ORGANIZATION';
    if(domain==='moddroid.com' && value==='contact@moddroid.com' && /app and game requests/i.test(c.evidence||''))return 'NON_OUTREACH_PURPOSE';
    if(REVIEW_PURPOSE.test(value.split('@')[0]))return 'NON_OUTREACH_PURPOSE';
    if(REVIEW_PLACEHOLDER.test(value)||/^[*\u2022]{3,}@/.test(value))return 'PLACEHOLDER';
    if(domain==='rutube.ru'&&/^(?:help|support)@/.test(value))return 'NON_OUTREACH_PURPOSE';
    if(domain==='samehadaku.care'&&value.endsWith('@poltekuniversity.us'))return 'UNEXPECTED_THIRD_PARTY_DOMAIN';
    const displayed=String(c.evidence||'').match(REVIEW_MAIL)||[];
    if(displayed.length&&!displayed.some(v=>v.toLowerCase()===value))return 'DISPLAY_LINK_MISMATCH';
  }
  return '';
}
const priorPublished=published;
published=c=>priorPublished(c)&&!explicitCommunity(c)&&!reviewReason(c);
const priorRender=render;
render=function(){
  priorRender();
  const explanations={
    SEO_SERVICE_CONTACT:'הכתובת משויכת לספק קידום אתרים; הסמכות לטפל במונטיזציה של האתר לא אומתה.',
    DOMAIN_SERVICE_CONTACT:'הכתובת משויכת לספק רישום דומיינים, ולא לאיש קשר עסקי מאומת של האתר.',
    INCOMPLETE_PHONE:'המספר שפורסם נראה חסר; נשמר לבדיקה ולא נספר כמסלול וואטסאפ לפנייה.',
    UNRELATED_HELP_ORGANIZATION:'ארגון סיוע חיצוני שמוזכר בעמוד, לא קונטקט של בעל האתר.',
    ADJACENT_SITE_SCOPE:'אתר משיק לפרופיל המבוקש; אינו נכלל ברשימת הפנייה המועדפת.',
    NON_OUTREACH_PURPOSE:'כתובת ייעודית למשפטי, פרטיות, תלונות, אבטחה או תפקיד אחר שאינו פנייה למונטיזציה.',
    PLACEHOLDER:'נראית ככתובת דוגמה; אינה קונטקט מומלץ לפנייה.',
    UNEXPECTED_THIRD_PARTY_DOMAIN:'כתובת בדומיין חיצוני בלתי צפוי; השיוך לאתר דורש בדיקה.',
    DISPLAY_LINK_MISMATCH:'כתובת הקישור שונה מהכתובת המוצגת בטקסט; יש לבדוק את המקור.'
  };
  const cards=$('cards').children;
  visible.forEach((g,i)=>{
    const reason=reviewReason(g.primary);
    if(reason&&cards[i])cards[i].append(element('p',explanations[reason],'warning'));
  });
};
