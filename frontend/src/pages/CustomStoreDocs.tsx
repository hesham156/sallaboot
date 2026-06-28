import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useSEO } from '../hooks/useSEO'

/* Small code block with RTL-safe LTR content. */
function Code({ children }: { children: string }) {
  return (
    <pre dir="ltr" className="bg-slate-900 text-slate-100 rounded-2xl p-4 overflow-x-auto text-[12px] leading-relaxed font-mono">
      <code>{children}</code>
    </pre>
  )
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)] relative overflow-hidden">
      {children}
    </div>
  )
}

const CATALOG_BODY = `{
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
}`

const EVENT_BODY = `{
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
}`

const NODE_SIGN = `const crypto = require("crypto");
const body = JSON.stringify(payload);            // sign the exact bytes you send
const sig  = crypto.createHmac("sha256", SIGNING_SECRET)
                   .update(body).digest("hex");
// header → X-Hayyak-Signature: sha256=\${sig}`

const CURL = `SECRET="whsec_..."
STORE_ID="abc123"
BODY='{"event":"order.created","data":{"id":"5012","total":360,"currency":"SAR","customer_phone":"0501234567","customer_name":"سارة"}}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')

curl -X POST "https://7ayak.app/webhooks/custom/$STORE_ID/events" \\
  -H "Content-Type: application/json" \\
  -H "X-Hayyak-Signature: sha256=$SIG" \\
  -d "$BODY"`

export default function CustomStoreDocs() {
  const navigate = useNavigate()
  useSEO({
    title:       'ربط متجر مبرمَج خاص | حياك',
    description: 'دليل المطوّر لربط متجر مبني ببرمجة خاصة بحياك عبر API موقّع — رفع الكتالوج، إرسال الأحداث، والتوقيع الأمني.',
  })

  return (
    <div dir="rtl" className="min-h-screen bg-slate-50/50 text-slate-800 font-sans pb-20 overflow-x-hidden">
      <div className="absolute top-[-6rem] right-[-6rem] w-[34rem] h-[34rem] bg-teal-300/20 rounded-full blur-[130px] pointer-events-none" />
      <div className="absolute top-[10rem] left-[-8rem] w-[30rem] h-[30rem] bg-cyan-300/15 rounded-full blur-[130px] pointer-events-none" />

      {/* Header */}
      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-slate-100">
        <nav className="max-w-5xl mx-auto px-6 h-16 flex items-center justify-between">
          <a href="/" className="flex items-center gap-2.5">
            <img src="/logo.png" style={{ maxWidth: '100%', height: 'auto', width: '140px' }} />
          </a>
          <button
            onClick={() => navigate('/')}
            className="inline-flex items-center gap-2 text-sm font-bold text-slate-700 bg-white border border-slate-200 rounded-full px-5 py-2 hover:border-teal-300 hover:text-teal-600 shadow-sm transition-all"
          >
            <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" className="rotate-180">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
            الرئيسية
          </button>
        </nav>
      </header>

      {/* Hero */}
      <div className="max-w-4xl mx-auto px-6 pt-16 pb-10 text-center">
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
          <span className="inline-block text-xs font-bold text-teal-600 bg-teal-50 rounded-full px-3.5 py-1.5 mb-4">
            دليل المطوّر
          </span>
          <h1 className="text-3xl sm:text-4xl font-black text-slate-900 leading-tight">
            ربط متجر <span className="text-gradient">مبرمَج خاص</span>
          </h1>
          <p className="text-slate-500 text-sm mt-3 max-w-2xl mx-auto leading-relaxed">
            متجرك مبني ببرمجة خاصة (مش على سلة/زد/شوبيفاي)؟ اربطه بحياك ليعمل عليه المساعد الذكي، الردود التلقائية،
            واسترجاع السلات المتروكة. الفكرة بسيطة: <b>متجرك يدفع البيانات إلى حياك</b> عبر طلبات HTTP موقّعة.
          </p>
        </motion.div>
      </div>

      {/* Content */}
      <div className="max-w-4xl mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1 }} className="space-y-6"
        >
          {/* Activation */}
          <Card>
            <div className="absolute top-0 left-0 w-2 h-full bg-gradient-to-b from-teal-500 to-cyan-500" />
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">⚡</span> ١. التفعيل
            </h2>
            <ol className="text-sm text-slate-600 leading-relaxed list-decimal mr-5 space-y-1.5">
              <li>من لوحة التحكم → <b>التكاملات</b> → <b>متجر مبرمَج خاص</b> → <b>تفعيل الربط</b>.</li>
              <li>انسخ <b>مفتاح التوقيع</b> (<code className="text-teal-600">signing_secret</code>) — يظهر <b>مرة واحدة فقط</b>. لو ضاع، ولّد مفتاحاً جديداً (يُلغي القديم فوراً).</li>
              <li>تظهر لك نقطتا الإرسال (endpoints) الخاصتان بمتجرك للكتالوج والأحداث.</li>
            </ol>
          </Card>

          {/* Auth */}
          <Card>
            <div className="absolute top-0 left-0 w-2 h-full bg-gradient-to-b from-amber-400 to-orange-500" />
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-3 flex items-center gap-2">
              <span className="text-amber-500 text-xl">🔐</span> ٢. المصادقة (في كل طلب)
            </h2>
            <p className="text-slate-600 text-sm leading-relaxed mb-3">
              وقّع <b>جسم الطلب الخام</b> بـ HMAC-SHA256 باستخدام <code className="text-teal-600">signing_secret</code>،
              وأرسله في الهيدر. طلب بدون توقيع صحيح يُرفض بـ <code>401</code>، ومتجر غير مُفعّل يُرفض بـ <code>404</code>.
            </p>
            <Code>{'X-Hayyak-Signature: sha256=<hex digest>\nContent-Type: application/json'}</Code>
            <p className="text-slate-600 text-sm font-bold mt-4 mb-2">مثال توليد التوقيع (Node.js):</p>
            <Code>{NODE_SIGN}</Code>
          </Card>

          {/* Catalog */}
          <Card>
            <div className="absolute top-0 left-0 w-2 h-full bg-gradient-to-b from-violet-500 to-indigo-500" />
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-2 flex items-center gap-2">
              <span className="text-violet-500 text-xl">📦</span> ٣. رفع الكتالوج الكامل
            </h2>
            <p className="text-slate-600 text-sm leading-relaxed mb-3">
              <code dir="ltr" className="text-violet-600 text-xs">POST /webhooks/custom/{'{store_id}'}/catalog</code>
              {' '}— استدعِه عند الربط أول مرة، وبعدها دورياً أو عند أي تغيير كبير. يستبدل الكتالوج المخزَّن بالكامل.
              الحقول مرنة (أسماء بديلة مقبولة: <code>title</code>, <code>sale_price</code>, <code>stock</code>, <code>images</code>…).
            </p>
            <Code>{CATALOG_BODY}</Code>
          </Card>

          {/* Events */}
          <Card>
            <div className="absolute top-0 left-0 w-2 h-full bg-gradient-to-b from-pink-500 to-rose-500" />
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-2 flex items-center gap-2">
              <span className="text-pink-500 text-xl">⚡</span> ٤. الأحداث اللحظية
            </h2>
            <p className="text-slate-600 text-sm leading-relaxed mb-3">
              <code dir="ltr" className="text-pink-600 text-xs">POST /webhooks/custom/{'{store_id}'}/events</code>
              {' '}— ابعث حدثاً واحداً عند حدوثه بالشكل <code dir="ltr">{'{ "event", "data" }'}</code>.
              الأحداث تُعالَج لا-تزامنياً مع منع التكرار، فإعادة الإرسال آمنة.
            </p>
            <div className="overflow-x-auto mb-4">
              <table className="w-full text-xs text-slate-600 border-collapse">
                <thead>
                  <tr className="border-b border-slate-200 text-slate-900">
                    <th className="text-right py-2 px-2 font-bold">الحدث</th>
                    <th className="text-right py-2 px-2 font-bold">الأثر في حياك</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  <tr><td className="py-2 px-2 font-mono" dir="ltr">product.created / updated</td><td className="py-2 px-2">تحديث الكتالوج فوراً</td></tr>
                  <tr><td className="py-2 px-2 font-mono" dir="ltr">product.deleted</td><td className="py-2 px-2">حذف المنتج من الكتالوج</td></tr>
                  <tr><td className="py-2 px-2 font-mono" dir="ltr">order.created</td><td className="py-2 px-2">رسالة تأكيد واتساب للعميل</td></tr>
                  <tr><td className="py-2 px-2 font-mono" dir="ltr">order.status_updated</td><td className="py-2 px-2">إشعار واتساب بتغيّر الحالة</td></tr>
                  <tr><td className="py-2 px-2 font-mono" dir="ltr">cart.abandoned</td><td className="py-2 px-2">تسجيلها + تذكير واتساب + إشعار التاجر</td></tr>
                </tbody>
              </table>
            </div>
            <Code>{EVENT_BODY}</Code>
          </Card>

          {/* Full example */}
          <Card>
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-3 flex items-center gap-2">
              <span className="text-teal-500 text-xl">🧪</span> مثال كامل (curl)
            </h2>
            <Code>{CURL}</Code>
            <ul className="text-slate-600 text-xs leading-relaxed list-disc mr-5 space-y-1 mt-4">
              <li>وقّع <b>نفس البايتات</b> التي ترسلها بالضبط (لا تُعِد تنسيق JSON بعد التوقيع).</li>
              <li>أرقام الجوال السعودية تُطبَّع تلقائياً إلى E.164 (<code dir="ltr">05x…</code> → <code dir="ltr">+9665x…</code>).</li>
              <li>رسائل الواتساب تُرسَل فقط إذا كان الواتساب مُفعّلاً في إعدادات المتجر.</li>
            </ul>
          </Card>

          <div className="bg-emerald-50 border border-emerald-100 rounded-3xl p-6 shadow-sm text-center">
            <p className="text-emerald-700 text-sm leading-relaxed">
              هل تحتاج مساعدة في الربط؟ راسلنا على{' '}
              <a href="mailto:support@7ayak.app" className="text-emerald-800 font-bold hover:underline">support@7ayak.app</a>
            </p>
          </div>
        </motion.div>
      </div>
    </div>
  )
}
