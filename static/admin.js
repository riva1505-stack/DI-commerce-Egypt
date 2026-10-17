(() => {
'use strict';
const qrTable=document.getElementById('qrTable'), qrImage=document.getElementById('qrImage'), qrLink=document.getElementById('qrDownload');
if(qrTable){qrTable.addEventListener('input',()=>{const n=Number(qrTable.value);if(!Number.isInteger(n)||n<Number(qrTable.min)||n>Number(qrTable.max))return;qrImage.src=`/qr/${n}.png`;qrImage.alt=`رمز QR للطاولة ${n}`;qrLink.href=`/qr/${n}.png`;qrLink.download=`table-${n}.png`})}
const btn=document.getElementById('refreshOrders');if(btn)btn.addEventListener('click',()=>location.reload());
const baseline=Number(document.querySelector('.admin-order .order-header')?.closest('.admin-order')?.querySelector('strong')?.textContent?0:0);
let lastSeen = null;
const poll=async()=>{try{const r=await fetch('/admin/pulse');if(!r.ok)return;const d=await r.json();document.getElementById('newStat').textContent=d.new_orders;document.getElementById('navNewCount').textContent=d.new_orders;if(lastSeen!==null&&d.last_order_id>lastSeen){document.getElementById('pollIndicator').textContent='· وصلت طلبات جديدة! اضغطي تحديث الطلبات.'}lastSeen=d.last_order_id;}catch(e){document.getElementById('pollIndicator').textContent='· الاتصال غير مستقر'}};
void baseline;poll();setInterval(poll,12000);
})();
