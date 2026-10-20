/* Bokharest reservation-page chat: independent from table/booking initialization. */
(() => {
  "use strict";
  function initialize() {
    const $ = id => document.getElementById(id);
    const form = $("chatForm"), input = $("chatInput"), thread = $("chatMessages");
    const send = $("sendChat"), suggestions = $("suggestions");
    const mic = $("micChat"), replay = $("listenChat"), info = $("voiceStatus");
    if (!form || !input || !thread || !send || !suggestions) return;
    let history = [], busy = false, latest = "", recognizer = null;
    let recognized = "", micTimer = null, readAfterMic = false;
    const Recognizer = window.SpeechRecognition || window.webkitSpeechRecognition;
    const canSpeak = Boolean(window.speechSynthesis && window.SpeechSynthesisUtterance);

    function bubble(message, fromUser = false) {
      const element = document.createElement("div");
      element.className = "bubble" + (fromUser ? " user" : "");
      element.textContent = String(message).slice(0, 1900);
      thread.append(element);
      thread.scrollTop = thread.scrollHeight;
      return element;
    }
    function speak(message) {
      if (!canSpeak) {
        if (info) info.textContent = "قراءة الرد غير مدعومة على المتصفح ده. الرد مكتوب فوق.";
        return;
      }
      try {
        window.speechSynthesis.cancel();
        const clean = String(message).replace(/[\u{1F300}-\u{1FAFF}\u2600-\u27BF]/gu, "")
          .replace(/(\d+)\.(\d{2}) (?:جنيه|ج\.م)/g, (_, pounds, piasters) =>
            Number(piasters) ? pounds + " جنيه و" + Number(piasters) + " قرش" : pounds + " جنيه")
          .slice(0, 650);
        const utterance = new SpeechSynthesisUtterance(clean);
        utterance.lang = "ar-EG";
        utterance.rate = 0.88;
        const voices = window.speechSynthesis.getVoices();
        const matching = voices.find(v => v.lang.toLowerCase() === "ar-eg")
          || voices.find(v => v.lang.toLowerCase().startsWith("ar"));
        if (matching) utterance.voice = matching;
        utterance.onerror = () => { if (info) info.textContent = "الصوت ما اشتغلش؛ الرد موجود مكتوب فوق."; };
        window.speechSynthesis.speak(utterance);
      } catch (_) {
        if (info) info.textContent = "تعذر تشغيل الصوت؛ الرد موجود مكتوب فوق.";
      }
    }
    async function ask(raw) {
      const question = String(raw || "").trim().slice(0, 300);
      if (!question || busy) return;
      busy = true;
      send.disabled = true;
      input.value = "";
      bubble(question, true);
      const pending = bubble("بشوف المنيو وأرد عليكي...");
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 12000);
      try {
        const response = await fetch("/api/bokharest/demo-chat", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({message: question, history: history.slice(-6)}),
          signal: controller.signal
        });
        let data;
        try { data = await response.json(); }
        catch (_) { throw Error("الرد مش واضح من السيرفر"); }
        if (!response.ok || !data || typeof data.text !== "string") {
          throw Error(typeof data?.detail === "string" ? data.detail : "الخدمة مش متاحة حاليًا");
        }
        pending.remove();
        const answer = data.text.slice(0, 1900);
        bubble(answer);
        history.push(question, answer);
        history = history.slice(-6);
        latest = answer;
        if (replay) replay.disabled = !canSpeak;
        if (info) info.textContent = "تم الرد. تقدري تسألي سؤال متابعة.";
        if (readAfterMic) speak(answer);
      } catch (error) {
        pending.remove();
        const detail = error?.name === "AbortError" ? "الرد اتأخر، جربي السؤال تاني" :
          (error?.message || "حصلت مشكلة في الاتصال");
        bubble("معلش، ماقدرتش أرد على السؤال: " + detail + ". ممكن تجربي تاني؟");
        if (info) info.textContent = "الشات واجه مشكلة، لكن تقدري تعيدي المحاولة بالكتابة.";
      } finally {
        clearTimeout(timer);
        readAfterMic = false;
        busy = false;
        send.disabled = false;
      }
    }
    form.addEventListener("submit", event => {
      event.preventDefault();
      ask(input.value);
    });
    suggestions.addEventListener("click", event => {
      const target = event.target.closest("button[data-prompt]");
      if (target) ask(target.dataset.prompt);
    });
    if (replay) {
      replay.disabled = !canSpeak;
      replay.addEventListener("click", () => { if (latest) speak(latest); });
    }
    if (mic) {
      if (!Recognizer) {
        mic.disabled = true;
        mic.title = "الميكروفون غير مدعوم هنا؛ اكتبي سؤالك";
      } else {
        mic.addEventListener("click", () => {
          if (busy) return;
          if (recognizer) {
            try { recognizer.stop(); } catch (_) {}
            return;
          }
          try {
            if (canSpeak) window.speechSynthesis.cancel();
            const rec = new Recognizer();
            recognizer = rec;
            recognized = "";
            rec.lang = "ar-EG";
            rec.continuous = false;
            rec.interimResults = false;
            rec.onstart = () => {
              mic.textContent = "🎙️ بسمعك...";
              mic.setAttribute("aria-pressed", "true");
            };
            rec.onresult = event => {
              recognized = event.results?.[0]?.[0]?.transcript || "";
            };
            rec.onerror = event => {
              recognized = "";
              if (info) info.textContent = event.error === "not-allowed"
                ? "اسمحي للمتصفح يستخدم الميكروفون، أو اكتبي السؤال."
                : "الصوت مش واضح. تقدري تجربي تاني أو تكتبي.";
            };
            rec.onend = () => {
              if (micTimer) clearTimeout(micTimer);
              micTimer = null;
              if (recognizer !== rec) return;
              recognizer = null;
              mic.textContent = "🎙️ اتكلمي";
              mic.setAttribute("aria-pressed", "false");
              const question = recognized;
              recognized = "";
              if (question) {
                readAfterMic = true;
                ask(question);
              }
            };
            rec.start();
            micTimer = setTimeout(() => {
              if (recognizer !== rec) return;
              try { rec.abort(); } catch (_) {}
              recognizer = null;
              recognized = "";
              mic.textContent = "🎙️ اتكلمي";
              mic.setAttribute("aria-pressed", "false");
              if (info) info.textContent = "الميكروفون اتوقف تلقائيًا. جربي مرة تانية أو اكتبي.";
              micTimer = null;
            }, 15000);
          } catch (_) {
            recognizer = null;
            mic.textContent = "🎙️ اتكلمي";
            if (info) info.textContent = "الميكروفون مش متاح. تقدري تستخدمي الكتابة.";
          }
        });
      }
    }
    if (info) info.textContent = "المساعد جاهز. اكتبي سؤالك واضغطي إرسال، أو اختاري سؤال من الاقتراحات.";
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, {once: true});
  } else {
    initialize();
  }
})();
