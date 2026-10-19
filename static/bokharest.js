(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const i18n = {
    ar: {
      demo:"تجربة طلبات بدون تنفيذ",greeting:"أهلاً بيك في",intro:"اختاري من المنيو، جرّبي السلة، وأكدي طلب تجريبي برقم الترابيزة — بدون إرسال طلب حقيقي.",
      menu:"المنيو",search:"ابحث عن صنف...",all:"كل الأقسام",items:"صنف",noItems:"لا توجد أصناف تطابق البحث.",
      important:"مهم قبل الطلب",legal:"هذه الصفحة معاينة للمنيو، وليست قناة لطلب الطعام. الأسعار من الصور المرسلة وقد تكون قديمة، وتحتاج تأكيد المطعم. للمكونات والحساسية اسأل موظف المطعم مباشرة.",
      back:"العودة للمشروع الرئيسي ←",testCart:"سلة التجربة",testOnly:"⚠️ تجربة داخلية: لن يُرسل طلب للمطعم الحقيقي، والأسعار تقديرية.",tableNo:"رقم الترابيزة",orderNote:"ملاحظة (اختياري)",sendDemo:"تأكيد الطلب التجريبي",notice:"الأسعار من صور المنيو المرسلة وتحتاج تأكيد المطعم؛ تنص الصور على رسم خدمة 12% وضريبة قيمة مضافة 14%. الطلبات هنا تجريبية فقط ولا تصل للمطعم.",
      error:"تعذّر تحميل المنيو حاليًا.",currency:"ج.م",preview:"معاينة",subHot:"ساخن",subCold:"بارد",subAvocado:"أفوكادو",subYogurt:"زبادي"
    },
    en: {
      demo:"Test orders only",greeting:"Welcome to",intro:"Browse the menu and test ordering by table number. No real restaurant orders are placed.",
      menu:"Menu",search:"Search items...",all:"All categories",items:"items",noItems:"No items match this search.",
      important:"Before ordering",legal:"This is a read-only menu preview, not an ordering service. Prices were transcribed from supplied photos and may be outdated; confirm with the restaurant. Ask staff about ingredients and allergies.",
      back:"Back to DI Commerce →",testCart:"Test cart",testOnly:"⚠️ Demo only: no order will reach the restaurant; prices are estimates.",tableNo:"Table number",orderNote:"Note (optional)",sendDemo:"Place test order",notice:"Prices are from supplied photos and require restaurant confirmation. The images state 12% service and 14% VAT. Test orders never reach the restaurant.",
      error:"Unable to load the menu.",currency:"EGP",preview:"Preview",subHot:"Hot",subCold:"Cold",subAvocado:"Avocado",subYogurt:"Yogurt"
    }
  };
  let lang = "ar", sections = [], active = "all", query = "";
  const t = k => (i18n[lang] || i18n.ar)[k] || k;
  const categoryLabel = c => c["name_"+lang], nameOf = i => i["name_"+lang] || i.name_ar;
  const descriptionOf = i => i["description_"+lang] || "";
  const fmt = price => (price / 100).toLocaleString(lang === "ar" ? "ar-EG" : "en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
  const subLabel = code => ({hot:t("subHot"),cold:t("subCold"),avocado:t("subAvocado"),yogurt:t("subYogurt")})[code] || "";
  function changeLang() {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
    document.querySelectorAll("[data-translate]").forEach(node=>{node.textContent=t(node.dataset.translate);});
    $("restaurantName").innerHTML = lang === "ar" ? "كافيه <em>بوخاريست</em>" : "Café <em>Bokharest</em>";
    $("taxNotice").textContent=t("notice");
    $("search").placeholder=t("search");
    $("search").setAttribute("aria-label",t("search"));
    document.title = lang === "ar" ? "كافيه بوخاريست | DI Commerce Egypt" : "Café Bokharest | DI Commerce Egypt";
    render();
  }
  function render() {
    const all = sections.flatMap(c=>c.items.map(i=>({...i,category:c.slug,emoji:c.emoji,catLabel:categoryLabel(c)})));
    const cats = [{slug:"all",label:t("all"),emoji:"✦"},...sections.map(c=>({slug:c.slug,label:categoryLabel(c),emoji:c.emoji}))];
    $("categories").innerHTML = cats.map(c=>'<button type="button" class="cat" data-cat="'+esc(c.slug)+'" aria-pressed="'+String(c.slug===active)+'">'+esc(c.emoji)+' '+esc(c.label)+'</button>').join("");
    const found = all.filter(i=>(active==="all"||i.category===active) && (!query || (i.name_ar+" "+i.name_en+" "+i.description_ar+" "+i.description_en).toLocaleLowerCase().includes(query)));
    $("menuCount").textContent = found.length+" "+t("items");
    $("menuGrid").innerHTML = found.length ? found.map(i=>'<article class="dish" data-item-id="'+esc(i.id)+'"><div class="dish-head"><div><h3>'+esc(nameOf(i))+'</h3><p class="english-name">'+esc(lang==="ar"?i.name_en:i.name_ar)+'</p></div><span class="dish-emoji" aria-hidden="true">'+esc(i.emoji)+'</span></div>'+(descriptionOf(i)?'<p class="description">'+esc(descriptionOf(i))+'</p>':'<p class="description"></p>')+'<div class="dish-foot"><span class="price" dir="ltr">'+esc(fmt(i.price_piasters))+' <small class="currency">'+t("currency")+'</small></span>'+(i.subsection?'<span class="subsection">'+esc(subLabel(i.subsection))+'</span>':'')+'<button type="button" class="dish-add" data-add-bokharest="'+esc(i.id)+'">'+(lang==="ar"?"أضف للسلة +":"Add to cart +")+'</button></div></article>').join("") : '<div class="empty">'+t("noItems")+'</div>';
  }
  async function load() {
    try {
      const response = await fetch("/static/data/bokharest_menu.json",{cache:"no-cache"});
      if (!response.ok) throw Error("menu fetch failed");
      const data = await response.json();
      if (data.restaurant?.slug !== "bokharest" || data.restaurant?.checkout_enabled !== false || !Array.isArray(data.categories)) throw Error("Invalid menu preview");
      sections = data.categories.filter(c=>Array.isArray(c.items));
      render();
    } catch (error) {
      $("menuGrid").innerHTML = '<div class="empty">'+t("error")+'</div>';
    }
  }
  $("language").addEventListener("change",event=>{
    lang = event.target.value === "en" ? "en" : "ar";
    try{localStorage.setItem("di-bokharest-language",lang);}catch(_){}
    changeLang();
  });
  $("search").addEventListener("input",event=>{query=event.target.value.trim().toLocaleLowerCase();render();});
  $("categories").addEventListener("click",event=>{
    const button=event.target.closest("button[data-cat]");
    if(button){active=button.dataset.cat;render();}
  });
  try{lang=localStorage.getItem("di-bokharest-language")==="en"?"en":"ar";}catch(_){}
  $("language").value=lang;
  changeLang();
  load();
})();
