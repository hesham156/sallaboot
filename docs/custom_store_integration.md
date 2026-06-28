# ربط متجر مبرمَج خصيصاً بحياك (Custom Store Integration)

دليل للمطوّرين الذين عندهم متجر مبني ببرمجة خاصة (مش على سلة/زد/شوبيفاي) ويريدون
ربطه بحياك (حياك / 7ayak.app) ليشتغل عليه المساعد الذكي، الردود التلقائية على
الواتساب، واسترجاع السلات المتروكة — تماماً مثل المنصات المدعومة.

## الفكرة

حياك ما عندهاش API تسحب منه بيانات متجرك المخصص، فبدل ما نسحب إحنا، **متجرك يدفع
(push)** البيانات لحياك عبر طلبات HTTP موقّعة. الذكاء الاصطناعي بعدها يشتغل على نفس
البنية الموحّدة المستخدمة لباقي المنصات.

> **مهم — هذا الدليل تكامل خادم‑لخادم (server‑to‑server) بحت.** متجرك يدفع
> الكتالوج والأحداث، وحياك يردّ على العملاء ويرسل التذكيرات **عبر واتساب**. لا
> يضيف هذا التكامل أي عنصر مرئي على صفحة متجرك — وهذا متوقّع. إذا أردت **فقاعة
> محادثة (chat widget) تظهر على موقعك**، فهي شيء منفصل تركّبه بسطر `<script>` —
> انظر قسم [الويدجت على الموقع](#الويدجت-على-الموقع-اختياري) في آخر الدليل.

## التفعيل

1. من لوحة تحكم حياك → **التكاملات** → **متجر مبرمَج خاص** → **تفعيل الربط**.
2. انسخ **مفتاح التوقيع** (`signing_secret`) — يظهر **مرة واحدة فقط**. لو ضاع منك،
   اعمل **توليد مفتاح جديد** (يلغي القديم فوراً).
3. تظهر لك نقطتا الربط (endpoints) الخاصتان بمتجرك:
   - `POST https://7ayak.app/webhooks/custom/{store_id}/catalog`
   - `POST https://7ayak.app/webhooks/custom/{store_id}/events`

## المصادقة (مطلوبة في كل طلب)

كل طلب لازم يحمل توقيع HMAC-SHA256 على **جسم الطلب الخام (raw body)** باستخدام
`signing_secret`، في هيدر:

```
X-Hayyak-Signature: sha256=<hex digest>
Content-Type: application/json
```

> طلب بدون توقيع صحيح يُرفض بـ `401`. متجر غير مُفعّل يُرفض بـ `404`.

مثال توليد التوقيع (Node.js):

```js
const crypto = require("crypto");
const body = JSON.stringify(payload);                 // وقّع نفس البايتات المرسلة
const sig  = crypto.createHmac("sha256", SIGNING_SECRET)
                   .update(body).digest("hex");
// header: X-Hayyak-Signature: `sha256=${sig}`
```

مثال (PHP):

```php
$body = json_encode($payload);
$sig  = hash_hmac('sha256', $body, $SIGNING_SECRET);
// header: X-Hayyak-Signature: sha256={$sig}
```

## ١) رفع الكتالوج الكامل — `/catalog`

استدعِه عند الربط أول مرة، وبعدها دورياً (مثلاً يومياً) أو عند أي تغيير كبير. يستبدل
الكتالوج المخزَّن بالكامل.

```json
{
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
      "description": "قميص قطن 100٪ مريح",
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
}
```

**حقول المنتج** (كلها مرنة، والأسماء البديلة مقبولة):

| الحقل | بديل مقبول | ملاحظات |
|---|---|---|
| `id` | — | مطلوب، نص أو رقم |
| `name` | `title` | اسم المنتج |
| `price` | `sale_price` | السعر الحالي |
| `regular_price` | `old_price`, `compare_price` | السعر قبل الخصم (اختياري) |
| `quantity` | `stock`, `available_quantity` | الكمية؛ أو `unlimited_quantity: true` |
| `categories` | `category` | قائمة نصوص أو `{name}` أو نص واحد |
| `image` | `images` | نص، أو قائمة نصوص/`{url\|src}` |
| `status` | — | اختياري: `sale` / `out` / `hidden` (وإلا يُحسب آلياً) |

الرد: `{ "status": "ok", "products": N, "categories": M }`.

## ٢) الأحداث اللحظية — `/events`

ابعث حدثاً واحداً عند حدوثه. الشكل العام:

```json
{ "event": "<اسم الحدث>", "data": { ... } }
```

### الأحداث المدعومة

| الحدث | `data` | الأثر في حياك |
|---|---|---|
| `product.created` / `product.updated` | كائن منتج (نفس شكل الكتالوج) | تحديث الكتالوج فوراً |
| `product.deleted` | `{ "id": "..." }` | حذف المنتج من الكتالوج |
| `order.created` | طلب (تحت) | رسالة تأكيد واتساب للعميل |
| `order.status_updated` | طلب + `status` | إشعار واتساب بتغيّر الحالة |
| `cart.abandoned` | سلة (تحت) | تسجيلها + تذكير واتساب + إشعار التاجر |

**كائن الطلب (`order.*`)**:

```json
{
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
}
```

**كائن السلة المتروكة (`cart.abandoned`)**:

```json
{
  "event": "cart.abandoned",
  "data": {
    "id": "cart-883",
    "customer_name": "سارة",
    "customer_phone": "+966501234567",
    "total": 250,
    "currency": "SAR",
    "items_count": 3,
    "checkout_url": "https://my-store.com/cart/883"
  }
}
```

الرد: `{ "status": "ok", "event": "<اسم الحدث>" }`. الأحداث تُعالَج لا-تزامنياً عبر
صندوق وارد مع منع التكرار (idempotent) — إعادة إرسال نفس الحدث آمنة.

## مثال كامل (curl)

```bash
SECRET="whsec_..."
STORE_ID="abc123"
BODY='{"event":"order.created","data":{"id":"5012","total":360,"currency":"SAR","customer_phone":"0501234567","customer_name":"سارة"}}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')

curl -X POST "https://7ayak.app/webhooks/custom/$STORE_ID/events" \
  -H "Content-Type: application/json" \
  -H "X-Hayyak-Signature: sha256=$SIG" \
  -d "$BODY"
```

## الويدجت على الموقع (اختياري)

كل ما سبق يعمل عبر واتساب بدون أي شيء على موقعك. لو أردت **فقاعة محادثة** على
صفحات متجرك (المساعد الذكي يردّ داخل الموقع نفسه، مع كروت المنتجات ورفع الملفات
والتقييم)، ركّب ويدجت حياك بسطرين — وهو مستقل تماماً عن مفتاح التوقيع وعن الـ
webhooks أعلاه (الويدجت يستخدم نقاط `/chat` العامة المقيّدة بالـ `storeId`).

```html
<!-- حياك — فقاعة المحادثة -->
<script>
  window.SallaChatConfig = {
    storeId: "YOUR_HAYYAK_STORE_ID",   // نفس store_id المستخدم في الـ webhooks
    apiUrl: "https://7ayak.app",       // اختياري — يُستنتج من مصدر السكربت
    primaryColor: "#12c2a0",
    storeName: "اسم متجرك"
  };
</script>
<script src="https://7ayak.app/widget.js" async></script>
```

### React / Next.js (App Router)

ضعه في `src/app/layout.tsx` (بجانب أي مُحقِّن سكربتات آخر) باستخدام `next/script`:

```tsx
import Script from "next/script"

// داخل <body>:
<Script id="hayyak-config" strategy="afterInteractive">
  {`window.SallaChatConfig = {
    storeId: "YOUR_HAYYAK_STORE_ID",
    apiUrl: "https://7ayak.app",
    primaryColor: "#12c2a0",
    storeName: "اسم متجرك"
  };`}
</Script>
<Script src="https://7ayak.app/widget.js" strategy="afterInteractive" />
```

| الإعداد | مطلوب؟ | الوصف |
|---|---|---|
| `storeId` | ✅ | معرّف متجرك في حياك — تجده في رابط اللوحة `…/store/{storeId}/…`، وهو نفسه المستخدم في الـ webhooks |
| `apiUrl` | ➖ | أصل خادم حياك؛ يُستنتج تلقائياً من مصدر السكربت إن تُرك فارغاً |
| `primaryColor` | ➖ | لون الويدجت (يُشتق منه التدرّج) |
| `storeName` | ➖ | الاسم الظاهر في رأس المحادثة |

> الويدجت يقرأ إعدادات الترحيب واللون أيضاً من لوحة حياك (`/chat/widget-config`)،
> فتعديلها من اللوحة ينعكس على الموقع دون تغيير الكود.

## ملاحظات

- وقّع **نفس البايتات** التي ترسلها بالضبط (لا تُعِد ترتيب/تنسيق JSON بعد التوقيع).
- أرقام الجوال السعودية تُطبَّع تلقائياً إلى صيغة E.164 (`05x…` → `+9665x…`).
- رسائل الواتساب تُرسَل فقط إذا كان الواتساب مُفعّلاً في إعدادات المتجر.
- لقطع الربط: من اللوحة، أو `DELETE /admin/{store_id}/integrations/custom`.
