'use strict';
// A public handle is not necessarily a person. Explicit source labels override
// ambiguous previews; a group-labelled route remains review-only.
function explicitCommunity(c){
  if(c.channel&&c.channel!=='telegram')return false;
  const text=String(c.evidence||'');
  if(/\b(owner|admin|manager|agent|developer)\b/i.test(text))return false;
  return /\btelegram\s+(?:support\s+)?(?:group|channel)\s*[.!]?$/i.test(text.trim());
}
const priorPublished=published;
published=c=>priorPublished(c)&&!explicitCommunity(c);
