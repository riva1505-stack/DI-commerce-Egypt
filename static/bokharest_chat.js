/* Bokharest's self-service, catalogue-grounded demo chat. No paid AI API. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const form = $("bokharestChatForm"), input = $("bokharestChatInput");
  const thread = $("bokharestChatMessages"), status = $("bokharestChatStatus");
  const send = $("bokharestChatSend"), voice = $("bokharestChatVoice");
  const mic = $("bokharestChatMic"), language = $("language");
  if (!form || !input || !thread || !send || !voice || !mic) return;
  const copy = {
    ar: {
      title:"🤖 اسألي مساعد بوخاريست", intro:"اسأليه عن الأكلات والمشروبات والأسعار؛ بيرد تلقائيًا من المنيو، من غير ما تحتاجي موظف يرد.",
      greeting:"أهلًا بيك في بوخاريست! 👋 عايز تعرف الموجود في المنيو، أو سعر صنف معين؟",
      placeholder:"مثلاً: عندكم فراخ؟ والسعر كام؟", send:"إرسال", listenOn:"🔊 قراءة الردود: شغالة",
      listenOff:"🔈 قراءة الردود: مقفولة", mic:"🎙️ اتكلمي", micBusy:"🎙️ بسمعك...",
      ready:"المساعد التجريبي يرد تلقائيًا من المنيو المسجل. مفيش حجز أو طلب حقيقي بيتم من الشات.",
      wait:"بيدور في منيو بوخاريست...", fail:"معلش، الرد مش متاح دلوقتي. جربي السؤال تاني.",
      limited:"الميكروفون مش متاح في المتصفح ده. اكتبي السؤال أو جرّبي متصفح بيدعم تحويل الكلام لنص.",
      voiceLimited:"ميزة قراءة الردود بصوت مش متاحة في المتصفح ده. تقدري تقري الرد هنا.",
      soundFail:"تعذر تشغيل الصوت على الجهاز. تقدري تقري الرد هنا.",
      micDenied:"الرجاء السماح للميكروفون من إعدادات المتصفح أو اكتبي سؤالك.",
      replay:"🔊 اسمع الرد", booking:"افتحي صفحة الحجز التجريبي", note:"هذه محاكاة. الأسعار تحتاج تأكيد المطعم؛ اسألي موظفًا عن الحساسية والمكونات.",
      suggestions:["عندكم فراخ؟","إيه المنيو؟","بكام البرجر؟","عايز أحجز ترابيزة"]
    },
    en: {
      title:"🤖 Ask Bokharest's menu assistant",intro:"Ask about dishes, drinks and prices. The assistant replies automatically using this demo menu.",
      greeting:"Welcome to Bokharest! 👋 Ask about anything listed on the menu or an item's price.",
      placeholder:"For example: Do you have chicken?",send:"Send",listenOn:"🔊 Read replies: on",
      listenOff:"🔈 Read replies: off",mic:"🎙️ Speak",micBusy:"🎙️ Listening...",
      ready:"Demo assistant: replies are grounded in the supplied menu. No real bookings or orders are made here.",
      wait:"Checking the Bokharest menu...",fail:"Sorry, I couldn't get an answer right now. Please try again.",
      limited:"Voice input isn't supported in this browser. Type your question instead.",
      voiceLimited:"Spoken replies aren't supported in this browser. You can read the response here.",
      soundFail:"Audio couldn't play on this device. You can read the response here.",
      micDenied:"Allow microphone access in your browser, or type your question.",
      replay:"🔊 Play reply",booking:"Open demo reservations",note:"Demo only. Confirm prices with the restaurant and ask staff about ingredients or allergens.",
      suggestions:["Do you have chicken?","What's on the menu?","How much is a burger?","I want a table"]
    }
  };
  const isEnglish = () => language && language.value === "en";
  const tr = k => copy[isEnglish() ? "en" : "ar"][k];
  let history = [], busy = false, autoRead = false, latest = "", recognizer = null;
  const canSpeak = Boolean(window.speechSynthesis && window.SpeechSynthesisUtterance);
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  function addMessage(text, fromCustomer = false, link = "") {
    const node = document.createElement("div");
    node.className = "bokharest-bubble" + (fromCustomer ? " from-customer" : " from-bot");
    node.textContent = String(text).slice(0, 1900);
    if (!fromCustomer) {
      const actions = document.createElement("div");
      actions.className = "bokharest-message-actions";
      if (canSpeak) {
        const replay = document.createElement("button");
        replay.type = "button"; replay.className = "bokharest-replay";
        replay.textContent = tr("replay");
        replay.addEventListener("click", () => speak(text));
        actions.append(replay);
      }
      if (link === "/bokharest/reserve") {
        const a = document.createElement("a");
        a.href = "/bokharest/reserve";
        a.textContent = tr("booking");
        actions.append(a);
      }
      if (actions.childNodes.length) node.append(actions);
    }
    thread.append(node);
    thread.scrollTop = thread.scrollHeight;
    return node;
  }
  function speak(text) {
    if (!canSpeak) { status.textContent = tr("voiceLimited"); return; }
    try {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(String(text).slice(0, 1250));
      utterance.lang = /[\u0600-\u06ff]/.test(text) ? "ar-EG" : "en-US";
      utterance.rate = 0.96;
      const available = window.speechSynthesis.getVoices();
      const matching = available.find(v => v.lang.toLowerCase().startsWith(utterance.lang.slice(0, 2)));
      if (matching) utterance.voice = matching;
      utterance.onerror = () => { status.textContent = tr("soundFail"); };
      window.speechSynthesis.speak(utterance);
    } catch (_) { status.textContent = tr("soundFail"); }
  }
  function localize() {
    $("bokharestChatTitle").textContent = tr("title");
    $("bokharestChatIntro").textContent = tr("intro");
    $("bokharestChatGreeting").textContent = tr("greeting");
    $("bokharestChatNote").textContent = tr("note");
    input.placeholder = tr("placeholder");
    input.setAttribute("aria-label", tr("title"));
    send.textContent = tr("send");
    voice.textContent = tr(autoRead ? "listenOn" : "listenOff");
    mic.textContent = tr("mic");
    document.querySelectorAll("[data-bokharest-question]").forEach((button, i) => {
      button.textContent = tr("suggestions")[i];
      button.dataset.bokharestQuestion = tr("suggestions")[i];
    });
    if (!busy) status.textContent = tr("ready");
  }
  async function ask(message) {
    message = String(message || "").trim().slice(0, 300);
    if (!message || busy) return;
    addMessage(message, true);
    input.value = ""; busy = true; send.disabled = true;
    status.textContent = tr("wait");
    const wait = addMessage(tr("wait"));
    try {
      const response = await fetch("/api/bokharest/demo-chat", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({message, history:history.slice(-6)})
      });
      const data = await response.json();
      if (!response.ok || typeof data.text !== "string") throw Error("invalid response");
      wait.remove();
      const reply = data.text.slice(0, 1900);
      addMessage(reply, false, data.link);
      latest = reply;
      history.push(message); history = history.slice(-6);
      status.textContent = tr("ready");
      if (autoRead) speak(reply);
    } catch (_) {
      wait.remove(); addMessage(tr("fail")); status.textContent = tr("fail");
    } finally {
      busy = false; send.disabled = false;
    }
  }
  form.addEventListener("submit", event => { event.preventDefault(); ask(input.value); });
  document.querySelectorAll("[data-bokharest-question]").forEach(button => {
    button.addEventListener("click", () => ask(button.dataset.bokharestQuestion));
  });
  voice.setAttribute("aria-pressed", "false");
  voice.addEventListener("click", () => {
    if (!canSpeak) { status.textContent = tr("voiceLimited"); return; }
    autoRead = !autoRead;
    voice.setAttribute("aria-pressed", String(autoRead));
    voice.textContent = tr(autoRead ? "listenOn" : "listenOff");
    if (!autoRead) window.speechSynthesis.cancel();
    else if (latest) speak(latest);
  });
  if (!Recognition) {
    mic.disabled = true;
    mic.title = tr("limited");
  } else {
    mic.addEventListener("click", () => {
      if (busy || recognizer) return;
      try {
        const rec = new Recognition();
        recognizer = rec; rec.lang = isEnglish() ? "en-US" : "ar-EG";
        rec.interimResults = false; rec.continuous = false;
        rec.onstart = () => { mic.textContent = tr("micBusy"); mic.setAttribute("aria-pressed", "true"); };
        rec.onresult = e => { const words = e.results?.[0]?.[0]?.transcript; if (words) ask(words); };
        rec.onerror = e => { status.textContent = e.error === "not-allowed" ? tr("micDenied") : tr("limited"); };
        rec.onend = () => { recognizer = null; mic.textContent = tr("mic"); mic.setAttribute("aria-pressed", "false"); };
        rec.start();
      } catch (_) { recognizer = null; status.textContent = tr("limited"); }
    });
  }
  language?.addEventListener("change", localize);
  localize();
})();