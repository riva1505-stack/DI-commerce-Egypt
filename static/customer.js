(() => {
'use strict';
const $ = (id) => document.getElementById(id);
let chatHistory = [], chatBusy = false, chatVoice = false, voiceRecognizer = null;
let voiceSession = false, voiceSessionVersion = 0, speechActive = false;
let voiceBackendStt = false, voiceBackendTts = false;
let mediaRecorder = null, micStream = null, recordTimer = null, recordChunks = [];
let currentAudio = null, currentAudioUrl = null, fallbackAudioUrl = null, recordingPending = false;
let menu = [], settings = {}, category = 'all', cart = [], modalItem = null, modalQty = 1, lastOrder = null, orderTimer = null, requestKey = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}-${Math.random()}`;
const fmt = (piasters) => (piasters / 100).toLocaleString('ar-EG', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ج.م';
const esc = (text) => String(text ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const stateLabels = {new:'بانتظار موافقة المطعم', accepted:'تم قبول الطلب', preparing:'قيد التحضير', ready:'طلبك جاهز', completed:'تم اكتمال الطلب', cancelled:'تم إلغاء الطلب'};
const urlTable = Number(new URLSearchParams(location.search).get('table'));

async function loadMenu(){
 try {
  const r = await fetch('/api/menu'); if(!r.ok) throw Error('تعذر تحميل المنيو');
  const data = await r.json(); menu = data.items; settings = data.settings;
  $('categoryTabs').innerHTML = `<button class="tab active" data-category="all">كل الأصناف</button>` + [...new Set(menu.map(x=>x.category))].map(x => `<button class="tab" data-category="${esc(x)}">${esc(x)}</button>`).join('');
  const tableLimit = Number(settings.table_count) || 20;
  $('tableNumber').max = tableLimit;
  if(Number.isInteger(urlTable) && urlTable >= 1 && urlTable <= tableLimit){$('tableNumber').value = urlTable; $('tableLabel').textContent = `رقم ${urlTable}`}
  else {$('tableLabel').textContent = 'حددي الرقم في السلة';}
  renderMenu(); renderCart();
 } catch (err) { $('menuGrid').innerHTML = `<div class="empty-panel">تعذر تحميل المنيو حاليًا. جرّبي تحديث الصفحة.</div>`; }
}
function renderMenu(){
 const q = ($('searchInput').value || '').trim().toLowerCase();
 const filtered = menu.filter(p => (category === 'all' || p.category === category) && (!q || `${p.name} ${p.description}`.toLowerCase().includes(q)));
 $('menuGrid').innerHTML = filtered.length ? filtered.map(p => `<article class="food-card" data-item-id="${p.id}"><div class="food-picture"><span class="food-emoji">${esc(p.emoji)}</span><span class="food-stamp">${esc(p.category)}</span></div><div class="food-copy"><div class="food-name"><h3>${esc(p.name)}</h3>${p.tags.includes('popular') ? '<span class="popular">★ الأكثر طلبًا</span>' : ''}</div><p>${esc(p.description)}</p><div class="food-bottom"><strong>${fmt(p.price_piasters)}</strong><button class="add-btn" type="button" data-add="${p.id}" aria-label="أضف ${esc(p.name)}">＋</button></div></div></article>`).join('') : '<div class="empty-panel">ما فيش أصناف مطابقة للبحث. جرّبي اختيار قسم مختلف.</div>';
}
function openModal(id){
 modalItem = menu.find(x=>x.id===id); if(!modalItem) return;
 modalQty=1; $('qtyValue').textContent='1'; $('modalTitle').textContent=modalItem.name; $('modalDesc').textContent=modalItem.description;
 $('modalAddons').innerHTML = modalItem.addons.length ? '<h4>إضافات اختيارية</h4>' + modalItem.addons.map(a => `<label class="addon-option"><span><input type="checkbox" value="${a.id}" data-addon="true"> ${esc(a.name)}</span><b>+ ${fmt(a.price_piasters)}</b></label>`).join('') : '<p class="muted">لا توجد إضافات متاحة لهذا الصنف.</p>';
 updateModalPrice(); $('addonModal').hidden=false; document.body.classList.add('no-scroll');
}
function checkedAddons(){return [...document.querySelectorAll('#modalAddons input:checked')].map(e=>Number(e.value)).sort((a,b)=>a-b)}
function updateModalPrice(){if(!modalItem)return;const ids=checkedAddons();let sum=modalItem.price_piasters+modalItem.addons.filter(a=>ids.includes(a.id)).reduce((s,a)=>s+a.price_piasters,0);$('modalPrice').textContent=fmt(sum*modalQty)}
function closeModal(){ $('addonModal').hidden=true; if($('cartDrawer').getAttribute('aria-hidden')==='true')document.body.classList.remove('no-scroll'); }
function renewKey(){requestKey=crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}-${Math.random()}`}
function addToCart(){
 if(!modalItem)return; const ids=checkedAddons(); const key = `${modalItem.id}|${ids.join(',')}`; const existing=cart.find(x=>x.key===key);
 if(existing){existing.quantity=Math.min(20,existing.quantity+modalQty)} else{cart.push({key,item_id:modalItem.id,addon_ids:ids,quantity:modalQty})}
 renewKey(); renderCart(); closeModal(); openCart();
}
function lineDetails(line){ const p=menu.find(x=>x.id===line.item_id); if(!p) return null;const selected = p.addons.filter(a=>line.addon_ids.includes(a.id));const unit=p.price_piasters+selected.reduce((sum,a)=>sum+a.price_piasters,0);return {p,selected,unit}; }
function subtotal(){return cart.reduce((sum,c)=>{const d=lineDetails(c);return sum+(d?d.unit*c.quantity:0)},0)}
function renderCart(){
 cart=cart.filter(c=>menu.some(p=>p.id===c.item_id));
 const count =cart.reduce((a,b)=>a+b.quantity,0);
 $('cartCount').textContent=count;$('cartCountTop').textContent=count;$('floatingTotal').textContent=fmt(subtotal());$('cartTotal').textContent=fmt(subtotal());
 $('floatingCart').classList.toggle('visible',count>0);
 $('cartLines').innerHTML = count ? cart.map((c,i)=>{const d=lineDetails(c);return `<div class="cart-line"><div class="cart-emoji">${esc(d.p.emoji)}</div><div class="cart-description"><b>${esc(d.p.name)}</b><small>${d.selected.length?d.selected.map(a=>esc(a.name)).join('، '):'بدون إضافات'}</small><strong>${fmt(d.unit*c.quantity)}</strong></div><div class="cart-controls"><button data-adjust="${i}:minus" aria-label="تقليل">−</button><b>${c.quantity}</b><button data-adjust="${i}:plus" aria-label="زيادة">+</button></div></div>`}).join('') : '<div class="cart-empty">🛒<p>سلتك فاضية حاليًا</p><small>اختار الأصناف اللي بتحبها من المنيو.</small></div>';
 $('submitOrder').disabled=count===0;
}
function openCart(){ $('cartDrawer').setAttribute('aria-hidden','false');$('overlay').hidden=false;document.body.classList.add('no-scroll');$('orderFeedback').textContent=''; }
function closeCart(){ $('cartDrawer').setAttribute('aria-hidden','true');$('overlay').hidden=true;document.body.classList.remove('no-scroll'); }
function feedback(message){ $('orderFeedback').textContent=message; }
async function submitOrder(){
 if(!cart.length)return; const table_no=Number($('tableNumber').value);
 if(!Number.isInteger(table_no)||table_no<1||table_no>Number(settings.table_count)){feedback(`أدخلي رقم طاولة بين 1 و ${settings.table_count}`);$('tableNumber').focus();return}
 const button=$('submitOrder');button.disabled=true;button.textContent='جاري إرسال الطلب...';feedback('');
 try{
  const body={table_no,note:$('orderNote').value.trim(),idempotency_key:requestKey,expected_total_piasters:subtotal(),items:cart.map(({item_id,quantity,addon_ids})=>({item_id,quantity,addon_ids}))};
  const r=await fetch('/api/orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await r.json();if(!r.ok){let message=typeof data.detail==='string'?data.detail:'تعذر إرسال الطلب';if(r.status===409){await loadMenu();}throw Error(message)}
  lastOrder=data;cart=[];renewKey();renderCart();closeCart();$('orderRef').textContent=data.reference;$('orderAmount').textContent=fmt(data.total_piasters);$('orderStatus').textContent=stateLabels[data.status]||data.status;$('successModal').hidden=false;document.body.classList.add('no-scroll');
  $('orderNote').value=''; if(orderTimer)clearInterval(orderTimer);orderTimer=setInterval(checkOrderStatus,7000);
 }catch(err){feedback(err.message||'حدث خطأ أثناء إرسال الطلب. جرّبي مرة أخرى.');}finally{button.disabled=!cart.length;button.textContent='تأكيد وإرسال الطلب ←';}
}
async function checkOrderStatus(){if(!lastOrder)return;try{const r=await fetch(`/api/orders/${encodeURIComponent(lastOrder.reference)}?token=${encodeURIComponent(lastOrder.tracking_token)}`);if(!r.ok)return;const d=await r.json();$('orderStatus').textContent=stateLabels[d.status]||d.status;if(['completed','cancelled'].includes(d.status)){clearInterval(orderTimer);orderTimer=null}}catch(e){/* network retries */}}
// Customer-assistant dialogue is independent of checkout. Only the real menu can enter the cart.
function chatLine(who, text, choices = []) {
 const thread = $('chatMessages');
 const line = document.createElement('div'); line.className = `chat-line ${who}`;
 if (who === 'bot') {const avatar = document.createElement('span'); avatar.className = 'chat-avatar'; avatar.textContent = '✳'; line.appendChild(avatar)}
 const bubble = document.createElement('div'); bubble.className = 'chat-bubble';
 const para = document.createElement('p'); para.textContent = text; bubble.appendChild(para);
 if (who === 'bot') {const replay = document.createElement('button');replay.type='button';replay.className='chat-replay';replay.setAttribute('data-read-chat','');replay.textContent='🔊 اسمع الرد';bubble.appendChild(replay)}
 if (choices.length) {
  const recs = document.createElement('div'); recs.className = 'chat-recommendations';
  choices.forEach(choice => {
   const product = menu.find(p => p.id === choice.id); if (!product) return;
   const btn = document.createElement('button'); btn.type = 'button'; btn.dataset.add = String(product.id);
   btn.innerHTML = `<span>${esc(product.emoji)} <b>${esc(product.name)}</b><small>${fmt(product.price_piasters)}</small></span><strong>＋ إضافة</strong>`;
   recs.appendChild(btn);
  });
  bubble.appendChild(recs);
 }
 line.appendChild(bubble); thread.appendChild(line); thread.scrollTop = thread.scrollHeight;
 return line;
}
function chatQuickReplies(replies) {
 $('chatChips').innerHTML = (replies || []).slice(0,4).map(v => `<button type="button" data-chat-reply="${esc(v)}">${esc(v)}</button>`).join('');
}
// Best cross-browser coverage: record with MediaRecorder and transcribe on the server.
// The browser's built-in recognition/speech synthesis remain optional fallbacks.
const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
const hasSpeechOut = Boolean(window.speechSynthesis && window.SpeechSynthesisUtterance);
const canRecord = Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
function canHearCustomer() { return Boolean((voiceBackendStt && canRecord) || SpeechRecognitionAPI); }
function canSpeakCustomer() { return Boolean(voiceBackendTts || hasSpeechOut); }
function setVoiceStatus(text) { $('chatVoiceStatus').textContent = text; }
function recordingNow() { return Boolean(mediaRecorder && mediaRecorder.state === 'recording'); }
function refreshVoiceControls() {
 const sessionButton=$('chatVoiceSession'), micActive=recordingNow() || Boolean(voiceRecognizer);
 sessionButton.setAttribute('aria-pressed',String(voiceSession));
 sessionButton.textContent=voiceSession?'■ إنهاء المحادثة الصوتية':'🎤 ابدأ محادثة صوتية';
 sessionButton.classList.toggle('active',voiceSession);
 $('chatVoiceToggle').setAttribute('aria-pressed',String(chatVoice));
 $('chatVoiceToggle').textContent=chatVoice?'🔊 صوت الردود: مفعّل':'🔈 صوت الردود: مغلق';
 $('chatMic').setAttribute('aria-pressed',String(micActive));
 $('chatMic').setAttribute('aria-label',micActive?'أوقف التسجيل وأرسل صوتك':'تحدث للكتابة في المحادثة');
 $('chatMic').classList.toggle('listening',micActive);
 $('chatMic').textContent=micActive?'🔴':'🎙️';
}
function releaseMic() {
 if(recordTimer){clearTimeout(recordTimer); recordTimer=null;}
 if(micStream){micStream.getTracks().forEach(track=>track.stop());micStream=null;}
}
function discardRecording() {
 if(mediaRecorder) {
  const recorder=mediaRecorder;mediaRecorder=null;
  recorder.onstop=null;recorder.ondataavailable=null;
  if(recorder.state!=='inactive')try{recorder.stop()}catch(_){}
 }
 recordChunks=[];recordingPending=false;releaseMic();
}
function finishRecording({submit=false}={}) {
 if(!recordingNow())return;
 const recorder=mediaRecorder;
 // Data is only sent after the user speaks and the recording has stopped.
 if(!submit){discardRecording();refreshVoiceControls();return}
 setVoiceStatus('بحوّل كلامك لنص دلوقتي...');
 if(recordTimer){clearTimeout(recordTimer);recordTimer=null;}
 try{recorder.stop()}catch(_){discardRecording();refreshVoiceControls()}
}
function stopListening() {
 const current=voiceRecognizer;voiceRecognizer=null;
 if(current)try{current.abort()}catch(_){}
 discardRecording();refreshVoiceControls();
}
function clearAudioFallback() {
 const element=$('chatAudioFallback');
 if(element){element.pause();element.removeAttribute('src');element.hidden=true;}
 if(fallbackAudioUrl){URL.revokeObjectURL(fallbackAudioUrl);fallbackAudioUrl=null;}
}
function cancelSpeech() {
 speechActive=false;
 if(currentAudio){currentAudio.onended=null;currentAudio.onerror=null;currentAudio.pause();currentAudio=null;}
 if(currentAudioUrl){URL.revokeObjectURL(currentAudioUrl);currentAudioUrl=null;}
 if(hasSpeechOut)try{window.speechSynthesis.cancel()}catch(_){}
}
function stopVoiceSession(message='المحادثة الصوتية متوقفة. يمكنك الكتابة في أي وقت.') {
 voiceSession=false;voiceSessionVersion+=1;
 stopListening();cancelSpeech();clearAudioFallback();refreshVoiceControls();setVoiceStatus(message);
}
function preferredMime() {
 const options=['audio/mp4','audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus','audio/ogg'];
 if(!MediaRecorder.isTypeSupported)return '';
 return options.find(type=>{try{return MediaRecorder.isTypeSupported(type)}catch(_){return false}})||'';
}
async function startRecording() {
 if(recordingNow() || recordingPending || chatBusy)return;
 if(!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)return startBrowserRecognition();
 recordingPending=true;refreshVoiceControls();
 const version=voiceSessionVersion;
 try {
  const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true},video:false});
  if(version!==voiceSessionVersion){stream.getTracks().forEach(track=>track.stop());return;}
  micStream=stream;const mime=preferredMime();
  const recorder=mime?new MediaRecorder(stream,{mimeType:mime}):new MediaRecorder(stream);
  mediaRecorder=recorder;recordChunks=[];
  recorder.ondataavailable=(event)=>{if(event.data && event.data.size)recordChunks.push(event.data)};
  recorder.onstop=async()=>{
   if(mediaRecorder!==recorder)return;
   const pieces=recordChunks.slice();recordChunks=[];mediaRecorder=null;releaseMic();refreshVoiceControls();
   if(!pieces.length || version!==voiceSessionVersion){setVoiceStatus('لم يُسجل صوت. اضغط الميكروفون وحاول تاني.');return}
   const mimeType=(recorder.mimeType || pieces[0]?.type || 'audio/webm').split(';')[0];
   const audio=new Blob(pieces,{type:mimeType});
   if(audio.size>2500000){setVoiceStatus('التسجيل كبير. حاول بجملة قصيرة.');return}
   try {
    const response=await fetch('/api/voice/transcribe',{method:'POST',headers:{'Content-Type':mimeType},body:audio});
    const data=await response.json();
    if(version!==voiceSessionVersion)return;
    if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'تعذر فهم الكلام.');
    const transcript=String(data.text||'').trim().slice(0,300);
    if(!transcript)throw Error('ما سمعتش جملة واضحة. جرّب تاني.');
    $('chatInput').value=transcript;
    setVoiceStatus('سمعتك، بجهز الرد...');
    sendChat(transcript);
   } catch(err){if(version===voiceSessionVersion)setVoiceStatus(err.message||'تعذر التعرف على الكلام. ممكن تكتب الطلب.');}
  };
  recorder.onerror=()=>{if(version===voiceSessionVersion)setVoiceStatus('تعذّر التسجيل. جرّب تاني أو استخدم الكتابة.');discardRecording();refreshVoiceControls()};
  recorder.start();
  recordTimer=setTimeout(()=>finishRecording({submit:true}),12000);
  setVoiceStatus('🎙️ بسمعك... اتكلم وبعدين اضغط الزر الأحمر للإرسال (بحد أقصى 12 ثانية).');
 } catch(err) {
  discardRecording();
  const blocked=['NotAllowedError','PermissionDeniedError','SecurityError'].includes(err?.name);
  setVoiceStatus(blocked?'اسمح للميكروفون من إعدادات المتصفح. يلزم HTTPS على الموقع.':'الميكروفون غير متاح؛ يمكنك الكتابة بدلًا منه.');
 } finally {recordingPending=false;refreshVoiceControls()}
}
function startBrowserRecognition() {
 if(!SpeechRecognitionAPI){setVoiceStatus('الكتابة متاحة، لكن إدخال الصوت يحتاج تفعيل الخدمة الصوتية على الخادم.');return}
 if(chatBusy||voiceRecognizer)return;
 let recognizer;
 try {
  recognizer=new SpeechRecognitionAPI();recognizer.lang='ar-EG';recognizer.continuous=false;recognizer.interimResults=true;
  voiceRecognizer=recognizer;refreshVoiceControls();setVoiceStatus('🎙️ بسمعك...');
  let delivered=false,finalText='';
  recognizer.onresult=event=>{
   let interim='';
   for(let i=event.resultIndex;i<event.results.length;i++){
    const piece=event.results[i][0]?.transcript||'';
    if(event.results[i].isFinal)finalText+=piece+' ';else interim+=piece;
   }
   $('chatInput').value=(finalText+interim).trim().slice(0,300);
   if(finalText.trim() && !delivered){delivered=true;const text=finalText.trim().slice(0,300);
    voiceRecognizer=null;try{recognizer.stop()}catch(_){}
    refreshVoiceControls();setVoiceStatus('سمعتك، بجهز الرد...');sendChat(text);
   }
  };
  recognizer.onerror=event=>{if(voiceRecognizer!==recognizer)return;
   const blocked=['not-allowed','service-not-allowed'].includes(event.error);
   if(blocked)stopVoiceSession('اسمح باستخدام الميكروفون من إعدادات المتصفح، أو اكتب طلبك.');
   else setVoiceStatus('تعذّر التعرف على الصوت. يمكنك كتابة طلبك بدلًا منه.');
  };
  recognizer.onend=()=>{if(voiceRecognizer!==recognizer)return;voiceRecognizer=null;refreshVoiceControls();
   if(!chatBusy)setVoiceStatus('اضغط الميكروفون للتحدث مرة أخرى.');
  };
  recognizer.start();
 }catch(_){voiceRecognizer=null;refreshVoiceControls();setVoiceStatus('تعذّر بدء الاستماع. اكتب طلبك.');}
}
function startListening() {
 if(chatBusy || recordingNow() || recordingPending || voiceRecognizer)return;
 cancelSpeech();
 if(voiceBackendStt && canRecord)startRecording();
 else startBrowserRecognition();
}
function audioComplete(version) {
 speechActive=false;
 if(currentAudio){currentAudio=null}
 if(currentAudioUrl){URL.revokeObjectURL(currentAudioUrl);currentAudioUrl=null}
 if(version!==voiceSessionVersion)return;
 if(voiceSession)startListening();
 else setVoiceStatus('الرد مكتوب أمامك. اكتب ردك أو اضغط الميكروفون.');
}
function browserSay(text,version) {
 if(!hasSpeechOut){setVoiceStatus('الصوت غير متاح الآن؛ الرد مكتوب أمامك.');return}
 try {
  const utterance=new SpeechSynthesisUtterance(String(text).slice(0,500));
  utterance.lang='ar-EG';utterance.rate=0.95;
  const voices=window.speechSynthesis.getVoices();
  utterance.voice=voices.find(v=>v.lang.toLowerCase()==='ar-eg')||voices.find(v=>v.lang.toLowerCase().startsWith('ar'))||null;
  speechActive=true;
  setVoiceStatus('🔊 المساعد بيتكلم، والرد مكتوب أمامك.');
  utterance.onend=()=>audioComplete(version);
  utterance.onerror=()=>{speechActive=false;setVoiceStatus('تعذّر الصوت على الجهاز. اضغط «اسمع الرد» أو اقرأ النص.');};
  window.speechSynthesis.speak(utterance);
 }catch(_){speechActive=false;setVoiceStatus('الصوت مش متاح حاليًا، لكن تقدر تقرأ الرد.');}
}
async function sayReply(text,{force=false}={}) {
 if((!chatVoice && !force)||!canSpeakCustomer())return;
 stopListening();cancelSpeech();clearAudioFallback();
 const version=voiceSessionVersion;
 if(voiceBackendTts){
  try {
   setVoiceStatus('بجهّز الرد الصوتي...');
   const response=await fetch('/api/voice/speak',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:String(text).slice(0,500)})});
   if(!response.ok)throw Error('الصوت الخارجي غير متاح');
   const blob=await response.blob();
   if(version!==voiceSessionVersion)return;
   currentAudioUrl=URL.createObjectURL(blob);
   const player=new Audio(currentAudioUrl);currentAudio=player;speechActive=true;
   player.onended=()=>audioComplete(version);
   player.onerror=()=>{cancelSpeech();browserSay(text,version)};
   await player.play();
   setVoiceStatus('🔊 المساعد بيتكلم بصوت، والنص ظاهر أمامك.');
   return;
  }catch(_){
   if(currentAudioUrl && version===voiceSessionVersion){
    // Mobile Safari may block async autoplay. A native control allows a direct tap.
    const fallback=$('chatAudioFallback');
    fallbackAudioUrl=currentAudioUrl;currentAudioUrl=null;currentAudio=null;speechActive=false;
    fallback.src=fallbackAudioUrl;fallback.hidden=false;
    fallback.onended=()=>{if(voiceSession && version===voiceSessionVersion)startListening()};
    setVoiceStatus('الرد الصوتي جاهز. اضغط ▶️ للاستماع، أو اقرأ الكلام المكتوب.');
    return;
   }
   cancelSpeech();if(version!==voiceSessionVersion)return;
  }
 }
 browserSay(text,version);
}
async function sendChat(message) {
 const text = String(message || '').trim().slice(0,300);
 if (!text || chatBusy) return;
 stopListening();cancelSpeech();
 chatBusy = true; $('chatSend').disabled = true; $('chatInput').value = ''; chatQuickReplies([]);
 chatLine('user',text); chatHistory.push({role:'user',content:text});
 // Don't grow server context forever; also avoids unnecessary model billing.
 chatHistory = chatHistory.slice(-19);
 const pending = chatLine('bot','بفكر في أنسب اختيارات ليك...');
 try {
  const r = await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages:chatHistory})});
  const answer = await r.json();
  if (!r.ok) throw Error(typeof answer.detail === 'string' ? answer.detail : 'حصل عطل مؤقت في المحادثة.');
  pending.remove(); chatLine('bot',answer.text,answer.choices||[]); chatQuickReplies(answer.quick_replies||[]);
  $('chatMode').textContent = answer.mode === 'ai' ? '✨ محادثة ذكاء اصطناعي' : 'محادثة إرشادية · بدون نموذج AI متصل';
  chatHistory.push({role:'assistant',content:String(answer.text).slice(0,500)});
  sayReply(answer.text);
 } catch (err) {
  pending.remove(); chatLine('bot',err.message||'حصلت مشكلة. ممكن نجرب تاني؟');
  if(voiceSession) stopVoiceSession('تعذّر جلب الرد. اكتب طلبك أو ابدأ المكالمة مجددًا.');
  chatHistory.pop(); chatQuickReplies(['بيتزا','برجر','حاجة خفيفة']);
 } finally { chatBusy = false; $('chatSend').disabled = false; if (!voiceSession) $('chatInput').focus(); }
}
function onChatForm(event) {event.preventDefault();sendChat($('chatInput').value)}
async function initChat() {
 try {
  const r=await fetch('/api/chat/config');const data=await r.json();
  voiceBackendStt=Boolean(data.voice_stt_enabled);voiceBackendTts=Boolean(data.voice_tts_enabled);
  $('chatMode').textContent=data.ai_enabled?'✨ AI متاح عند اتصال الخدمة':'محادثة إرشادية · لتفعيل AI يلزم مفتاح على الخادم';
  $('chatPrivacy').textContent=voiceBackendStt?'عند تشغيل الميكروفون يُرسل التسجيل مؤقتًا إلى خادم المطعم ومزود الصوت لتحويله لنص. لا تُسجّل بيانات حساسة. الحساسية الغذائية تُراجع مع الموظف.':'الميكروفون لا يعمل إلا بإذنك؛ قد يستخدم التعرف الصوتي خدمات المتصفح. لا تشارك بيانات حساسة.';
 }catch(_){$('chatMode').textContent='محادثة إرشادية';}
 $('chatVoiceToggle').disabled=!canSpeakCustomer();
 $('chatMic').disabled=!canHearCustomer();
 $('chatVoiceSession').disabled=!(canHearCustomer()&&canSpeakCustomer());
 if(!canHearCustomer())setVoiceStatus('الكتابة متاحة دائمًا. لتفعيل الصوت على هذا المتصفح يلزم ربط خدمة الصوت بالخادم.');
 else if(!canSpeakCustomer())setVoiceStatus('تقدر تملي الطلب بالصوت وتقرأ الرد؛ الصوت المسموع يحتاج تفعيل خدمة الصوت.');
 else if(voiceBackendStt&&voiceBackendTts)setVoiceStatus('جاهز للصوت والكتابة على المتصفحات الحديثة. اسمح للميكروفون عند الطلب.');
 else setVoiceStatus('الكتابة متاحة. الصوت يعتمد على إمكانيات متصفحك حتى يتم تفعيل الخدمة الخارجية.');
 refreshVoiceControls();
}
function toggleVoiceSession() {
 if(voiceSession){stopVoiceSession();return;}
 if(!canHearCustomer()||!canSpeakCustomer())return;
 voiceSession=true;voiceSessionVersion+=1;chatVoice=true;refreshVoiceControls();
 // Audio may require a further user tap on some mobile browsers; text stays usable.
 sayReply('أهلاً بيك! أنا مساعد المطعم. تحب تاكل إيه النهارده؟',{force:true});
}
function onMicrophoneClick() {
 if(recordingNow()){finishRecording({submit:true});return;}
 if(voiceRecognizer){stopListening();setVoiceStatus('وقفت الاستماع. يمكنك الكتابة أو الضغط للمتابعة.');return;}
 if(chatBusy||recordingPending)return;
 chatVoice=canSpeakCustomer();refreshVoiceControls();startListening();
}

document.addEventListener('click',e=>{
 const add=e.target.closest('[data-add]');if(add){openModal(Number(add.dataset.add));return}
 const tab=e.target.closest('[data-category]');if(tab){category=tab.dataset.category;document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b===tab));renderMenu();return}
 const action=e.target.closest('[data-adjust]');if(action){let[i,what]=action.dataset.adjust.split(':');i=Number(i);if(!cart[i])return;cart[i].quantity+=what==='plus'?1:-1;cart[i].quantity=Math.min(20,cart[i].quantity);if(cart[i].quantity<1)cart.splice(i,1);renewKey();renderCart();return}
 const chip=e.target.closest('[data-chat-reply]');if(chip){sendChat(chip.dataset.chatReply);return}
 const replay=e.target.closest('[data-read-chat]');if(replay){const text=replay.closest('.chat-bubble')?.querySelector('p')?.textContent;if(text){chatVoice=true;refreshVoiceControls();sayReply(text,{force:true})}return}
 if(e.target.closest('[data-close-modal]'))closeModal();
});
$('searchInput').addEventListener('input',renderMenu);$('openCartTop').addEventListener('click',openCart);$('floatingCart').addEventListener('click',openCart);$('closeCart').addEventListener('click',closeCart);$('overlay').addEventListener('click',closeCart);$('closeModal').addEventListener('click',closeModal);$('heroAsk').addEventListener('click',()=>{$('assistant').scrollIntoView({behavior:'smooth'});$('chatInput').focus()});
$('modalAddons').addEventListener('change',updateModalPrice);$('qtyMinus').addEventListener('click',()=>{modalQty=Math.max(1,modalQty-1);$('qtyValue').textContent=modalQty;updateModalPrice()});$('qtyPlus').addEventListener('click',()=>{modalQty=Math.min(20,modalQty+1);$('qtyValue').textContent=modalQty;updateModalPrice()});$('confirmAddon').addEventListener('click',addToCart);$('submitOrder').addEventListener('click',submitOrder);$('chatForm').addEventListener('submit',onChatForm);$('chatMic').addEventListener('click',onMicrophoneClick);$('chatVoiceSession').addEventListener('click',toggleVoiceSession);$('chatVoiceToggle').addEventListener('click',()=>{chatVoice=!chatVoice;if(!chatVoice){stopVoiceSession('الصوت متوقف؛ الكتابة متاحة.')}refreshVoiceControls();});
$('closeSuccess').addEventListener('click',()=>{$('successModal').hidden=true;document.body.classList.remove('no-scroll')});
loadMenu(); initChat();
})();
