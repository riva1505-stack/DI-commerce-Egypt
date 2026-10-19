/* DI Commerce Egypt customer-facing language selection.
   No API key or restaurant data is stored in the browser. */
(() => {
  "use strict";
  const translations = {
    ar: {
      pilot:"نسخة تجريبية",welcome:"أهلاً بيك في",what:"نفسك في إيه",today:"النهارده؟",
      heroDesc:"منيو على مزاجك، ترشيحات تساعدك تختار، وطلبك يوصل للمطعم في خطوات بسيطة.",
      explore:"استكشف المنيو",helpChoose:"✨ ساعدني أختار",
      clearPrices:"✦ أسعار واضحة",noInstall:"✦ بدون تحميل تطبيق",payCash:"✦ الدفع عند الكاشير",
      smartHelper:"✦ مساعدك الذكي على الطاولة",voiceTextMenu:"صوت + كتابة + منيو",
      chatTitle:"اسألني واختار على ذوقك",
      chatDesc:"نتكلم عن اللي بتحبه وميزانيتك، وأقترح لك وجبات من منيو المطعم بأسعارها المسجلة.",
      menuEyebrow:"THE MENU · القائمة",allDishes:"كل حاجة",appetising:"تفتح النفس",
      stepTitle:"من أول اختيارك لحد الطاولة",
      step1:"اختار من المنيو",step1small:"واختار إضافاتك",
      step2:"راجع و أكّد",step2small:"السعر يتراجع من النظام",
      step3:"طلبك يصل للمطعم",step3small:"والدفع عند الكاشير",
      cartTitle:"سلة الطلبات",tableNum:"رقم الطاولة",note:"ملاحظة للمطعم (اختياري)",
      subtotal:"الإجمالي",sendOrder:"تأكيد وإرسال الطلب ←",
      searchPlaceholder:"ابحث عن صنف...",chatPlaceholder:"مثلاً: نفسي في وجبة خفيفة لحد 200 جنيه",
      all:"كل الأصناف",send:"إرسال ←",startVoice:"🎤 ابدأ محادثة صوتية",
      stopVoice:"■ إنهاء المحادثة الصوتية",readOn:"🔊 صوت الردود: مفعّل",
      readOff:"🔈 صوت الردود: مغلق",greeting:"أهلاً بيك! 😄 تحب تاكل إيه النهارده؟",
      pizza:"🍕 بيتزا",burger:"🍔 برجر",light:"🥗 حاجة خفيفة",drinks:"🥤 مشروبات",
      askStaff:"للحساسية الغذائية راجع موظف المطعم.",waiting:"بانتظار موافقة المطعم"
    },
    en: {
      pilot:"Demo version",welcome:"Welcome to",what:"What are you craving",today:"today?",
      heroDesc:"Explore the menu, discover recommendations and send your order to the restaurant in just a few steps.",
      explore:"Explore menu",helpChoose:"✨ Help me choose",
      clearPrices:"✦ Clear prices",noInstall:"✦ No app needed",payCash:"✦ Pay at the cashier",
      smartHelper:"✦ Your smart table assistant",voiceTextMenu:"Voice + Chat + Menu",
      chatTitle:"Ask me anything about the menu",
      chatDesc:"Tell me your preferences and budget. I'll suggest dishes listed on this restaurant's menu.",
      menuEyebrow:"THE MENU",allDishes:"Something",appetising:"delicious",
      stepTitle:"From choosing to ordering",
      step1:"Choose from the menu",step1small:"Customise your order",
      step2:"Review and confirm",step2small:"We validate prices before checkout",
      step3:"Order sent to staff",step3small:"Pay at the cashier",
      cartTitle:"Your cart",tableNum:"Table number",note:"Order note (optional)",
      subtotal:"Total",sendOrder:"Confirm and send order →",
      searchPlaceholder:"Search the menu...",chatPlaceholder:"For example: something light under 200 EGP",
      all:"All items",send:"Send →",startVoice:"🎤 Start voice chat",
      stopVoice:"■ End voice chat",readOn:"🔊 Voice replies: on",
      readOff:"🔈 Voice replies: off",greeting:"Welcome! 😄 What would you like to order?",
      pizza:"🍕 Pizza",burger:"🍔 Burger",light:"🥗 Something light",drinks:"🥤 Drinks",
      askStaff:"Please ask staff about food allergies.",waiting:"Awaiting restaurant approval"
    },
    fr: {
      pilot:"Version démo",welcome:"Bienvenue chez",what:"Une petite envie",today:"aujourd’hui ?",
      heroDesc:"Explorez le menu, découvrez nos suggestions et envoyez votre commande au restaurant en quelques étapes.",
      explore:"Voir le menu",helpChoose:"✨ Aidez-moi à choisir",
      clearPrices:"✦ Prix affichés",noInstall:"✦ Sans application",payCash:"✦ Paiement en caisse",
      smartHelper:"✦ Votre assistant à table",voiceTextMenu:"Voix + Chat + Menu",
      chatTitle:"Posez vos questions sur le menu",
      chatDesc:"Dites-moi vos envies et votre budget. Je suggère des plats présents sur le menu du restaurant.",
      menuEyebrow:"LA CARTE",allDishes:"Des choix",appetising:"savoureux",
      stepTitle:"Du choix à la commande",
      step1:"Choisissez un plat",step1small:"Personnalisez vos options",
      step2:"Vérifiez et confirmez",step2small:"Les prix sont vérifiés avant validation",
      step3:"Commande envoyée",step3small:"Paiement en caisse",
      cartTitle:"Votre panier",tableNum:"Numéro de table",note:"Note pour le restaurant (facultatif)",
      subtotal:"Total",sendOrder:"Confirmer et envoyer →",
      searchPlaceholder:"Rechercher un plat...",chatPlaceholder:"Par exemple : un plat léger à moins de 200 EGP",
      all:"Tous les plats",send:"Envoyer →",startVoice:"🎤 Démarrer la conversation",
      stopVoice:"■ Terminer la conversation",readOn:"🔊 Réponses vocales : oui",
      readOff:"🔈 Réponses vocales : non",greeting:"Bienvenue ! 😄 Que souhaitez-vous commander ?",
      pizza:"🍕 Pizza",burger:"🍔 Burger",light:"🥗 Plat léger",drinks:"🥤 Boissons",
      askStaff:"Consultez le personnel en cas d'allergie.",waiting:"En attente du restaurant"
    }
  };
  const key = "di-commerce-language-v1";
  const allowed = ["ar-eg","ar-lb","en","fr"];
  let choice = "ar-eg";
  try { const saved = localStorage.getItem(key); if (allowed.includes(saved)) choice = saved; } catch (_) {}
  function current() {
    return {language:choice.startsWith("ar") ? "ar" : choice,
      dialect:choice === "ar-lb" ? "lebanese" : "egyptian",
      speechLanguage:choice === "en" ? "en-US" : choice === "fr" ? "fr-FR" : choice === "ar-lb" ? "ar-LB" : "ar-EG"};
  }
  function t(id) {
    return (translations[current().language] || translations.ar)[id] || translations.ar[id] || id;
  }
  function apply() {
    const locale = current(), select = document.getElementById("diLanguage");
    if (select) select.value = choice;
    document.documentElement.lang = locale.language;
    document.documentElement.dir = locale.language === "ar" ? "rtl" : "ltr";
    document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    document.title = "DI Commerce Egypt · " + (document.querySelector(".eyebrow")?.textContent || "");
  }
  function setChoice(next) {
    if (!allowed.includes(next) || next === choice) return;
    choice = next;
    try { localStorage.setItem(key, choice); } catch (_) {}
    apply();
    document.dispatchEvent(new CustomEvent("di:locale-change", {detail:current()}));
  }
  window.DI18n = Object.freeze({current,t,apply,setChoice});
  document.addEventListener("DOMContentLoaded", () => {
    const select = document.getElementById("diLanguage");
    if (select) select.addEventListener("change", () => setChoice(select.value));
    apply();
  });
})();
