(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
  const ui = {
    ar: {
      cart: "سلة التجربة", empty: "السلة فاضية. اختاري صنف من المنيو.",
      remove: "حذف", table: "رقم الترابيزة", subtotal: "الأصناف",
      service: "الخدمة 12% (تقديري)", vat: "الضريبة 14% (تقديري)",
      total: "الإجمالي التقريبي", send: "تأكيد الطلب التجريبي",
      noTable: "اكتبي رقم الترابيزة بين 1 و500.", noItems: "اختاري صنف واحد على الأقل.",
      error: "تعذّر تسجيل التجربة. راجعي اتصال الإنترنت وحاولي تاني.",
      updated: "جاري حساب الإجمالي...", submitting: "بنحفظ الطلب التجريبي...",
      success: "اتسجل الطلب التجريبي رقم", note: "الطلب مش هيروح للمطعم الحقيقي.",
      noWa: "إشعارات واتساب التلقائية لسه مش متوصلة.",
      waSent: "خدمة واتساب قبلت رسالة التنبيه، ووصولها بيتأكد من مزوّد الخدمة.",
      waFail: "الطلب اتسجل، لكن إرسال تنبيه واتساب فشل.",
      cur: "ج.م", add: "اتضاف للسلة", loading: "جاري تحميل المنيو..."
    },
    en: {
      cart: "Test cart", empty: "Your cart is empty. Pick an item from the menu.",
      remove: "Remove", table: "Table number", subtotal: "Items",
      service: "12% service (estimate)", vat: "14% VAT (estimate)",
      total: "Estimated total", send: "Place test order",
      noTable: "Enter a table number from 1 to 500.", noItems: "Select at least one item.",
      error: "Unable to save the demo order. Check your connection and try again.",
      updated: "Calculating the total...", submitting: "Saving test order...",
      success: "Test order saved:", note: "Nothing has been sent to the real restaurant.",
      noWa: "Automatic WhatsApp notifications are not configured yet.",
      waSent: "The WhatsApp provider accepted the notification; delivery is not yet confirmed.",
      waFail: "Test order saved, but the WhatsApp notification failed.",
      cur: "EGP", add: "Added to cart", loading: "Loading menu..."
    }
  };
  const lang = () => $("language").value === "en" ? "en" : "ar";
  const t = key => ui[lang()][key];
  const money = value => (value / 100).toLocaleString(lang() === "ar" ? "ar-EG" : "en-US",
    {minimumFractionDigits:2, maximumFractionDigits:2}) + " " + t("cur");
  const sessionKey = "di-bokharest-demo-cart-v1";
  const overlay = $("demoCartOverlay"), panel = $("demoCartPanel");
  const cart = new Map();
  let menu = new Map(), quote = null, quoteSerial = 0, isSending = false, lastFocus = null;
  const button = $("demoSubmit");
  const getLines = () => [...cart].map(([item_id,quantity]) => ({item_id,quantity}));
  const message = (str, bad = false) => {
    $("demoCartMessage").textContent = str || "";
    $("demoCartMessage").classList.toggle("error", Boolean(bad));
  };
  function loadCart() {
    try {
      const data = JSON.parse(sessionStorage.getItem(sessionKey) || "[]");
      if (Array.isArray(data)) for (const [id, qty] of data.slice(0, 40)) {
        if (Number.isInteger(id) && id > 0 && Number.isInteger(qty) && qty > 0 && qty <= 20) {
          cart.set(id, qty);
        }
      }
    } catch (_) { /* private browsing can disable storage */ }
  }
  function saveCart() {
    try { sessionStorage.setItem(sessionKey, JSON.stringify([...cart])); } catch (_) {}
  }
  function openCart() {
    lastFocus = document.activeElement;
    panel.hidden = false;
    overlay.hidden = false;
    document.body.classList.add("demo-cart-open");
    renderCart();
    $("closeDemoCart").focus();
  }
  function closeCart() {
    panel.hidden = true;
    overlay.hidden = true;
    document.body.classList.remove("demo-cart-open");
    if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
  }
  function renderCart() {
    const count = [...cart.values()].reduce((a, b) => a + b, 0);
    $("demoCartBadge").textContent = count;
    const items = [...cart].filter(([id]) => menu.has(id));
    $("demoCartLines").innerHTML = items.length ? items.map(([id, qty]) => {
      const item = menu.get(id);
      const name = item["name_" + lang()] || item.name_ar;
      return '<div class="demo-line"><div class="demo-line-title"><strong>' +
        escapeHtml(name) + '</strong><small>' + escapeHtml(money(item.price_piasters * qty)) +
        '</small></div><div class="demo-quantity"><button type="button" data-cart-minus="' + id +
        '" aria-label="-">−</button><b>' + qty + '</b><button type="button" data-cart-plus="' + id +
        '" aria-label="+">+</button><button type="button" class="demo-remove" data-cart-remove="' +
        id + '">' + t("remove") + '</button></div></div>';
    }).join("") : '<p class="demo-cart-empty">' + t("empty") + '</p>';
    $("demoSubmit").textContent = t("send");
    if (items.length) {
      $("demoCartTotals").innerHTML = quote ? [
        [t("subtotal"), quote.subtotal_piasters], [t("service"), quote.service_piasters],
        [t("vat"), quote.vat_piasters], [t("total"), quote.total_piasters]
      ].map(([label, value], i) => '<div class="demo-total-row' + (i===3?' grand':'') +
        '"><span>'+escapeHtml(label)+'</span><strong>'+escapeHtml(money(value))+'</strong></div>').join("")
        : '<p>' + t("updated") + '</p>';
    } else {
      $("demoCartTotals").innerHTML = "";
    }
    button.disabled = !items.length || !quote || isSending;
  }
  async function refreshQuote() {
    const serial = ++quoteSerial;
    quote = null;
    renderCart();
    if (!cart.size || !menu.size) return;
    try {
      const response = await fetch("/api/bokharest/quote", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({items:getLines()})
      });
      if (!response.ok) throw Error("quote unavailable");
      const result = await response.json();
      if (serial !== quoteSerial) return;
      quote = result;
      renderCart();
    } catch (_) {
      if (serial !== quoteSerial) return;
      message(t("error"), true);
      renderCart();
    }
  }
  function setQty(id, qty) {
    if (!menu.has(id)) return;
    if (qty <= 0) cart.delete(id);
    else if (qty <= 20) cart.set(id, qty);
    saveCart();
    message("");
    void refreshQuote();
  }
  async function submit() {
    if (isSending) return;
    if (!cart.size || !quote) { message(t("noItems"), true); return; }
    const table = Number($("demoTable").value);
    if (!Number.isInteger(table) || table < 1 || table > 500) {
      message(t("noTable"), true); $("demoTable").focus(); return;
    }
    isSending = true;
    const payload = {
      items:getLines(), table_no:table, note:$("demoNote").value.slice(0,250),
      expected_total_piasters:quote.total_piasters,
      idempotency_key:crypto.randomUUID ? crypto.randomUUID() :
        Date.now().toString(36) + Math.random().toString(36).slice(2) + "demoonly"
    };
    renderCart();
    message(t("submitting"));
    try {
      const response = await fetch("/api/bokharest/demo-orders", {
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(payload)
      });
      const result = await response.json();
      if (!response.ok) throw Error(typeof result.detail === "string" ? result.detail : t("error"));
      cart.clear(); saveCart(); quote = null; ++quoteSerial;
      $("demoNote").value = "";
      const wa = result.alert_status === "accepted_by_provider" ? t("waSent")
        : result.alert_status === "failed" ? t("waFail") : t("noWa");
      renderCart();
      message(t("success") + " " + result.reference + ". " + t("note") + " " + wa);
    } catch (err) {
      message(err.message || t("error"), true);
    } finally {
      isSending = false;
      renderCart();
    }
  }
  $("openDemoCart").addEventListener("click", openCart);
  $("closeDemoCart").addEventListener("click", closeCart);
  overlay.addEventListener("click", closeCart);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !panel.hidden) closeCart();
    if (event.key === "Tab" && !panel.hidden) {
      const elems = [...panel.querySelectorAll('button:not(:disabled),input,textarea')].filter(el => !el.hidden);
      if (!elems.length) return;
      const first=elems[0], last=elems[elems.length - 1];
      if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last.focus();}
      else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first.focus();}
    }
  });
  $("menuGrid").addEventListener("click", event => {
    const add = event.target.closest("[data-add-bokharest]");
    if (!add) return;
    const id = Number(add.dataset.addBokharest);
    if (!menu.has(id)) return;
    setQty(id, (cart.get(id) || 0) + 1);
    openCart();
    message(t("add"));
  });
  $("demoCartLines").addEventListener("click", event => {
    const el = event.target.closest("button");
    if (!el) return;
    if (el.dataset.cartMinus) { const id=Number(el.dataset.cartMinus); setQty(id,(cart.get(id)||0)-1); }
    if (el.dataset.cartPlus) { const id=Number(el.dataset.cartPlus); setQty(id,(cart.get(id)||0)+1); }
    if (el.dataset.cartRemove) setQty(Number(el.dataset.cartRemove),0);
  });
  button.addEventListener("click", submit);
  $("language").addEventListener("change", () => {
    document.querySelectorAll('[data-demo-label]').forEach(el => {
      const key=el.dataset.demoLabel;
      el.textContent = t(key);
    });
    if (!panel.hidden) renderCart();
    else $("demoCartBadge").textContent = [...cart.values()].reduce((a,b)=>a+b,0);
  });
  async function load() {
    try {
      const response = await fetch("/static/data/bokharest_menu.json", {cache:"no-cache"});
      if (!response.ok) throw Error("menu unavailable");
      const data = await response.json();
      if (data.restaurant?.slug !== "bokharest" || !Array.isArray(data.categories)) throw Error("invalid menu");
      menu = new Map(data.categories.flatMap(c => c.items).map(i => [i.id, i]));
      for (const id of cart.keys()) if (!menu.has(id)) cart.delete(id);
      saveCart();
      await refreshQuote();
      if (panel.hidden) renderCart();
    } catch (_) { message(t("error"), true); }
  }
  const selectedTable = Number(new URLSearchParams(location.search).get("table"));
  if (Number.isInteger(selectedTable) && selectedTable > 0 && selectedTable <= 500) {
    $("demoTable").value = selectedTable;
  }
  loadCart();
  renderCart();
  void load();
})();