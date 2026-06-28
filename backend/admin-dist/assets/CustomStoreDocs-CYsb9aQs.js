import{f as r,j as e}from"./react-CQhVsFhe.js";import{u as i}from"./useSEO-AX0jF6_n.js";import{p as l}from"./heroui-D_J42r8J.js";function t({children:a}){return e.jsx("pre",{dir:"ltr",className:"bg-slate-900 text-slate-100 rounded-2xl p-4 overflow-x-auto text-[12px] leading-relaxed font-mono",children:e.jsx("code",{children:a})})}function s({children:a}){return e.jsx("div",{className:"bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)] relative overflow-hidden",children:a})}const c=`{
  "store": {
    "name": "متجر الأناقة",
    "domain": "https://my-store.com",
    "currency": "SAR",
    "email": "owner@my-store.com",
    "description": "متجر ملابس وإكسسوارات"
  },
  "products": [
    {
      "id": "1001",
      "name": "قميص قطن",
      "description": "قميص قطن 100% مريح",
      "price": 120,
      "regular_price": 150,
      "sku": "SHIRT-001",
      "quantity": 8,
      "categories": ["ملابس رجالية", "قمصان"],
      "image": "https://my-store.com/img/shirt.jpg",
      "url": "https://my-store.com/products/shirt-001",
      "options": [{ "option": "المقاس", "values": ["S", "M", "L"] }]
    }
  ],
  "categories": [{ "id": "c1", "name": "ملابس رجالية" }]
}`,d=`{
  "event": "order.created",
  "data": {
    "id": "5012",
    "reference_id": "#5012",
    "total": 360,
    "currency": "SAR",
    "status": "قيد المعالجة",
    "customer_name": "سارة",
    "customer_phone": "0501234567"
  }
}`,n=`const crypto = require("crypto");
const body = JSON.stringify(payload);            // sign the exact bytes you send
const sig  = crypto.createHmac("sha256", SIGNING_SECRET)
                   .update(body).digest("hex");
// header → X-Hayyak-Signature: sha256=\${sig}`,o=`<!-- حياك — فقاعة المحادثة -->
<script>
  window.SallaChatConfig = {
    storeId: "YOUR_HAYYAK_STORE_ID",   // نفس store_id المستخدم في الـ webhooks
    apiUrl: "https://7ayak.app",
    primaryColor: "#12c2a0",
    storeName: "اسم متجرك"
  };
<\/script>
<script src="https://7ayak.app/widget.js" async><\/script>`,x=`import Script from "next/script"

// داخل <body> في src/app/layout.tsx:
<Script id="hayyak-config" strategy="afterInteractive">
  {\`window.SallaChatConfig = {
    storeId: "YOUR_HAYYAK_STORE_ID",
    apiUrl: "https://7ayak.app",
    primaryColor: "#12c2a0",
    storeName: "اسم متجرك"
  };\`}
<\/Script>
<Script src="https://7ayak.app/widget.js" strategy="afterInteractive" />`,m=`SECRET="whsec_..."
STORE_ID="abc123"
BODY='{"event":"order.created","data":{"id":"5012","total":360,"currency":"SAR","customer_phone":"0501234567","customer_name":"سارة"}}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')

curl -X POST "https://7ayak.app/webhooks/custom/$STORE_ID/events" \\
  -H "Content-Type: application/json" \\
  -H "X-Hayyak-Signature: sha256=$SIG" \\
  -d "$BODY"`;function b(){const a=r();return i({title:"ربط متجر مبرمَج خاص | حياك",description:"دليل المطوّر لربط متجر مبني ببرمجة خاصة بحياك عبر API موقّع — رفع الكتالوج، إرسال الأحداث، والتوقيع الأمني."}),e.jsxs("div",{dir:"rtl",className:"min-h-screen bg-slate-50/50 text-slate-800 font-sans pb-20 overflow-x-hidden",children:[e.jsx("div",{className:"absolute top-[-6rem] right-[-6rem] w-[34rem] h-[34rem] bg-teal-300/20 rounded-full blur-[130px] pointer-events-none"}),e.jsx("div",{className:"absolute top-[10rem] left-[-8rem] w-[30rem] h-[30rem] bg-cyan-300/15 rounded-full blur-[130px] pointer-events-none"}),e.jsx("header",{className:"sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-slate-100",children:e.jsxs("nav",{className:"max-w-5xl mx-auto px-6 h-16 flex items-center justify-between",children:[e.jsx("a",{href:"/",className:"flex items-center gap-2.5",children:e.jsx("img",{src:"/logo.png",style:{maxWidth:"100%",height:"auto",width:"140px"}})}),e.jsxs("button",{onClick:()=>a("/"),className:"inline-flex items-center gap-2 text-sm font-bold text-slate-700 bg-white border border-slate-200 rounded-full px-5 py-2 hover:border-teal-300 hover:text-teal-600 shadow-sm transition-all",children:[e.jsx("svg",{width:15,height:15,viewBox:"0 0 24 24",fill:"none",stroke:"currentColor",strokeWidth:2.5,strokeLinecap:"round",strokeLinejoin:"round",className:"rotate-180",children:e.jsx("path",{d:"M5 12h14M12 5l7 7-7 7"})}),"الرئيسية"]})]})}),e.jsx("div",{className:"max-w-4xl mx-auto px-6 pt-16 pb-10 text-center",children:e.jsxs(l.div,{initial:{opacity:0,y:20},animate:{opacity:1,y:0},transition:{duration:.5},children:[e.jsx("span",{className:"inline-block text-xs font-bold text-teal-600 bg-teal-50 rounded-full px-3.5 py-1.5 mb-4",children:"دليل المطوّر"}),e.jsxs("h1",{className:"text-3xl sm:text-4xl font-black text-slate-900 leading-tight",children:["ربط متجر ",e.jsx("span",{className:"text-gradient",children:"مبرمَج خاص"})]}),e.jsxs("p",{className:"text-slate-500 text-sm mt-3 max-w-2xl mx-auto leading-relaxed",children:["متجرك مبني ببرمجة خاصة (مش على سلة/زد/شوبيفاي)؟ اربطه بحياك ليعمل عليه المساعد الذكي، الردود التلقائية، واسترجاع السلات المتروكة. الفكرة بسيطة: ",e.jsx("b",{children:"متجرك يدفع البيانات إلى حياك"})," عبر طلبات HTTP موقّعة."]})]})}),e.jsx("div",{className:"max-w-4xl mx-auto px-6",children:e.jsxs(l.div,{initial:{opacity:0,y:30},animate:{opacity:1,y:0},transition:{duration:.6,delay:.1},className:"space-y-6",children:[e.jsxs(s,{children:[e.jsx("div",{className:"absolute top-0 left-0 w-2 h-full bg-gradient-to-b from-teal-500 to-cyan-500"}),e.jsxs("h2",{className:"text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2",children:[e.jsx("span",{className:"text-teal-500 text-xl",children:"⚡"})," ١. التفعيل"]}),e.jsxs("ol",{className:"text-sm text-slate-600 leading-relaxed list-decimal mr-5 space-y-1.5",children:[e.jsxs("li",{children:["من لوحة التحكم → ",e.jsx("b",{children:"التكاملات"})," → ",e.jsx("b",{children:"متجر مبرمَج خاص"})," → ",e.jsx("b",{children:"تفعيل الربط"}),"."]}),e.jsxs("li",{children:["انسخ ",e.jsx("b",{children:"مفتاح التوقيع"})," (",e.jsx("code",{className:"text-teal-600",children:"signing_secret"}),") — يظهر ",e.jsx("b",{children:"مرة واحدة فقط"}),". لو ضاع، ولّد مفتاحاً جديداً (يُلغي القديم فوراً)."]}),e.jsx("li",{children:"تظهر لك نقطتا الإرسال (endpoints) الخاصتان بمتجرك للكتالوج والأحداث."})]})]}),e.jsxs(s,{children:[e.jsx("div",{className:"absolute top-0 left-0 w-2 h-full bg-gradient-to-b from-amber-400 to-orange-500"}),e.jsxs("h2",{className:"text-lg sm:text-xl font-black text-slate-900 mb-3 flex items-center gap-2",children:[e.jsx("span",{className:"text-amber-500 text-xl",children:"🔐"})," ٢. المصادقة (في كل طلب)"]}),e.jsxs("p",{className:"text-slate-600 text-sm leading-relaxed mb-3",children:["وقّع ",e.jsx("b",{children:"جسم الطلب الخام"})," بـ HMAC-SHA256 باستخدام ",e.jsx("code",{className:"text-teal-600",children:"signing_secret"}),"، وأرسله في الهيدر. طلب بدون توقيع صحيح يُرفض بـ ",e.jsx("code",{children:"401"}),"، ومتجر غير مُفعّل يُرفض بـ ",e.jsx("code",{children:"404"}),"."]}),e.jsx(t,{children:`X-Hayyak-Signature: sha256=<hex digest>
Content-Type: application/json`}),e.jsx("p",{className:"text-slate-600 text-sm font-bold mt-4 mb-2",children:"مثال توليد التوقيع (Node.js):"}),e.jsx(t,{children:n})]}),e.jsxs(s,{children:[e.jsx("div",{className:"absolute top-0 left-0 w-2 h-full bg-gradient-to-b from-violet-500 to-indigo-500"}),e.jsxs("h2",{className:"text-lg sm:text-xl font-black text-slate-900 mb-2 flex items-center gap-2",children:[e.jsx("span",{className:"text-violet-500 text-xl",children:"📦"})," ٣. رفع الكتالوج الكامل"]}),e.jsxs("p",{className:"text-slate-600 text-sm leading-relaxed mb-3",children:[e.jsxs("code",{dir:"ltr",className:"text-violet-600 text-xs",children:["POST /webhooks/custom/","{store_id}","/catalog"]})," ","— استدعِه عند الربط أول مرة، وبعدها دورياً أو عند أي تغيير كبير. يستبدل الكتالوج المخزَّن بالكامل. الحقول مرنة (أسماء بديلة مقبولة: ",e.jsx("code",{children:"title"}),", ",e.jsx("code",{children:"sale_price"}),", ",e.jsx("code",{children:"stock"}),", ",e.jsx("code",{children:"images"}),"…)."]}),e.jsx(t,{children:c})]}),e.jsxs(s,{children:[e.jsx("div",{className:"absolute top-0 left-0 w-2 h-full bg-gradient-to-b from-pink-500 to-rose-500"}),e.jsxs("h2",{className:"text-lg sm:text-xl font-black text-slate-900 mb-2 flex items-center gap-2",children:[e.jsx("span",{className:"text-pink-500 text-xl",children:"⚡"})," ٤. الأحداث اللحظية"]}),e.jsxs("p",{className:"text-slate-600 text-sm leading-relaxed mb-3",children:[e.jsxs("code",{dir:"ltr",className:"text-pink-600 text-xs",children:["POST /webhooks/custom/","{store_id}","/events"]})," ","— ابعث حدثاً واحداً عند حدوثه بالشكل ",e.jsx("code",{dir:"ltr",children:'{ "event", "data" }'}),". الأحداث تُعالَج لا-تزامنياً مع منع التكرار، فإعادة الإرسال آمنة."]}),e.jsx("div",{className:"overflow-x-auto mb-4",children:e.jsxs("table",{className:"w-full text-xs text-slate-600 border-collapse",children:[e.jsx("thead",{children:e.jsxs("tr",{className:"border-b border-slate-200 text-slate-900",children:[e.jsx("th",{className:"text-right py-2 px-2 font-bold",children:"الحدث"}),e.jsx("th",{className:"text-right py-2 px-2 font-bold",children:"الأثر في حياك"})]})}),e.jsxs("tbody",{className:"divide-y divide-slate-100",children:[e.jsxs("tr",{children:[e.jsx("td",{className:"py-2 px-2 font-mono",dir:"ltr",children:"product.created / updated"}),e.jsx("td",{className:"py-2 px-2",children:"تحديث الكتالوج فوراً"})]}),e.jsxs("tr",{children:[e.jsx("td",{className:"py-2 px-2 font-mono",dir:"ltr",children:"product.deleted"}),e.jsx("td",{className:"py-2 px-2",children:"حذف المنتج من الكتالوج"})]}),e.jsxs("tr",{children:[e.jsx("td",{className:"py-2 px-2 font-mono",dir:"ltr",children:"order.created"}),e.jsx("td",{className:"py-2 px-2",children:"رسالة تأكيد واتساب للعميل"})]}),e.jsxs("tr",{children:[e.jsx("td",{className:"py-2 px-2 font-mono",dir:"ltr",children:"order.status_updated"}),e.jsx("td",{className:"py-2 px-2",children:"إشعار واتساب بتغيّر الحالة"})]}),e.jsxs("tr",{children:[e.jsx("td",{className:"py-2 px-2 font-mono",dir:"ltr",children:"cart.abandoned"}),e.jsx("td",{className:"py-2 px-2",children:"تسجيلها + تذكير واتساب + إشعار التاجر"})]})]})]})}),e.jsx(t,{children:d})]}),e.jsxs(s,{children:[e.jsxs("h2",{className:"text-lg sm:text-xl font-black text-slate-900 mb-3 flex items-center gap-2",children:[e.jsx("span",{className:"text-teal-500 text-xl",children:"🧪"})," مثال كامل (curl)"]}),e.jsx(t,{children:m}),e.jsxs("ul",{className:"text-slate-600 text-xs leading-relaxed list-disc mr-5 space-y-1 mt-4",children:[e.jsxs("li",{children:["وقّع ",e.jsx("b",{children:"نفس البايتات"})," التي ترسلها بالضبط (لا تُعِد تنسيق JSON بعد التوقيع)."]}),e.jsxs("li",{children:["أرقام الجوال السعودية تُطبَّع تلقائياً إلى E.164 (",e.jsx("code",{dir:"ltr",children:"05x…"})," → ",e.jsx("code",{dir:"ltr",children:"+9665x…"}),")."]}),e.jsx("li",{children:"رسائل الواتساب تُرسَل فقط إذا كان الواتساب مُفعّلاً في إعدادات المتجر."})]})]}),e.jsxs(s,{children:[e.jsx("div",{className:"absolute top-0 left-0 w-2 h-full bg-gradient-to-b from-cyan-500 to-teal-500"}),e.jsxs("h2",{className:"text-lg sm:text-xl font-black text-slate-900 mb-2 flex items-center gap-2",children:[e.jsx("span",{className:"text-cyan-500 text-xl",children:"💬"})," الويدجت على الموقع (اختياري)"]}),e.jsxs("p",{className:"text-slate-600 text-sm leading-relaxed mb-3",children:["كل ما سبق يعمل عبر واتساب بدون أي شيء على موقعك. لو أردت ",e.jsx("b",{children:"فقاعة محادثة"})," ","تظهر على صفحات متجرك (المساعد الذكي يردّ داخل الموقع نفسه)، ركّبها بسطرين — وهي مستقلة عن مفتاح التوقيع وعن الـ webhooks (تستخدم نقاط ",e.jsx("code",{dir:"ltr",children:"/chat"})," ","العامة المقيّدة بالـ ",e.jsx("code",{children:"storeId"}),")."]}),e.jsx(t,{children:o}),e.jsx("p",{className:"text-slate-600 text-sm font-bold mt-4 mb-2",children:"React / Next.js (App Router):"}),e.jsx(t,{children:x}),e.jsxs("ul",{className:"text-slate-600 text-xs leading-relaxed list-disc mr-5 space-y-1 mt-4",children:[e.jsxs("li",{children:[e.jsx("code",{children:"storeId"})," هو نفسه المستخدم في الـ webhooks — تجده في رابط اللوحة ",e.jsx("code",{dir:"ltr",children:"…/store/{storeId}/…"}),"."]}),e.jsxs("li",{children:[e.jsx("code",{children:"apiUrl"})," اختياري؛ يُستنتج تلقائياً من مصدر السكربت."]}),e.jsx("li",{children:"إعدادات الترحيب واللون تُقرأ أيضاً من لوحة حياك، فتعديلها ينعكس دون تغيير الكود."})]})]}),e.jsx("div",{className:"bg-emerald-50 border border-emerald-100 rounded-3xl p-6 shadow-sm text-center",children:e.jsxs("p",{className:"text-emerald-700 text-sm leading-relaxed",children:["هل تحتاج مساعدة في الربط؟ راسلنا على"," ",e.jsx("a",{href:"mailto:support@7ayak.app",className:"text-emerald-800 font-bold hover:underline",children:"support@7ayak.app"})]})})]})})]})}export{b as default};
