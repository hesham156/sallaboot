import type { ReactNode } from 'react'

/* ──────────────────────────────────────────────────────────────────
   Blog post registry.

   Add a new post:
     1. Append a `PostMeta` entry to POSTS below (newest first).
     2. Add the slug → JSX component mapping in POST_CONTENT.
     3. (Optional) Run `npm run build` and update the backend sitemap
        in routers/public.py to include the new slug.

   Why a single file: each article is a JSX component (rich layout
   inline) and we want one place to grep for "every post we've ever
   shipped." If the registry grows past ~20 posts, split by year.

   SEO note: titles aim for the search query a Salla merchant would
   type. Avoid clickbait — match search intent. Descriptions appear
   in Google SERPs as the snippet, so write them for humans not bots.
─────────────────────────────────────────────────────────────────── */

export interface PostMeta {
  slug:        string   // URL: /blog/:slug
  title:       string   // <title> tag + H1 + card
  description: string   // meta description + card excerpt (~150 chars)
  date:        string   // ISO yyyy-mm-dd — published date
  readTime:    number   // minutes (estimate: words / 200)
  tags:        string[] // for filtering + internal linking
  author?:     string
}

export const POSTS: PostMeta[] = [
  {
    slug:        'how-to-add-whatsapp-bot-to-salla-store',
    title:       'كيف تربط بوت واتساب بمتجر سلة في ٥ دقائق — الدليل الشامل ٢٠٢٦',
    description: 'دليل خطوة بخطوة لتفعيل بوت واتساب الذكي على متجر سلة الخاص بك. اكتشف كيف يرد البوت على عملائك تلقائياً ٢٤/٧ ويزيد مبيعاتك بدون أي خبرة تقنية.',
    date:        '2026-06-13',
    readTime:    6,
    tags:        ['بوت سلة', 'واتساب أعمال', 'دليل تعليمي'],
    author:      'فريق حياك',
  },
  {
    slug:        'recover-abandoned-carts-whatsapp',
    title:       '١٠ طرق مجرّبة لاسترجاع السلات المتروكة في متجر سلة',
    description: '٧٠٪ من العملاء يتركون سلاتهم بدون شراء. اكتشف ١٠ استراتيجيات عملية لاسترجاعهم عبر واتساب وزيادة مبيعاتك ٢٠-٣٠٪ في الشهر الأول.',
    date:        '2026-06-12',
    readTime:    8,
    tags:        ['سلات متروكة', 'واتساب', 'مبيعات'],
    author:      'فريق حياك',
  },
]

/* ─── Article content ─────────────────────────────────────────────
   Tailwind classes use the `prose` pattern for typography.
   Keep H2/H3 structure consistent so the TOC + on-page navigation
   stay predictable.
──────────────────────────────────────────────────────────────────── */

/* Inline styling — we don't have @tailwindcss/typography installed,
   so emulate `prose` with a scoped <style> block. Each article wraps
   itself in `article-body` and inherits these rules. */
const ArticleStyles = () => (
  <style>{`
    .article-body { color: #334155; }
    .article-body p { line-height: 2.1; margin: 1.1rem 0; font-size: 1.05rem; }
    .article-body p.lead { font-size: 1.18rem; color: #64748b; margin-top: 0; }
    .article-body h2 { font-size: 1.85rem; font-weight: 900; color: #0f172a; margin-top: 3rem; margin-bottom: 1rem; line-height: 1.3; }
    .article-body h3 { font-size: 1.3rem; font-weight: 800; color: #0f172a; margin-top: 2rem; margin-bottom: .75rem; line-height: 1.4; }
    .article-body strong { color: #0f172a; font-weight: 700; }
    .article-body a { color: #0d9488; font-weight: 700; text-decoration: none; border-bottom: 1px dashed #5eead4; }
    .article-body a:hover { border-bottom-style: solid; color: #0f766e; }
    .article-body ul, .article-body ol { margin: 1rem 0; padding-right: 1.5rem; }
    .article-body li { line-height: 2; margin: .4rem 0; font-size: 1.02rem; }
    .article-body ul li { list-style: disc; }
    .article-body ol li { list-style: decimal; }
    .article-body code { color: #0f766e; background: #ccfbf1; padding: 2px 8px; border-radius: 4px; font-size: .9em; font-family: ui-monospace, monospace; direction: ltr; display: inline-block; }
    .article-body blockquote { margin: 1.5rem 0; padding: 1rem 1.25rem; background: #f0fdfa; border-right: 4px solid #14b8a6; border-radius: 6px; color: #134e4a; font-style: italic; }
    .article-body blockquote p { margin: 0; }
  `}</style>
)

function Article({ children }: { children: ReactNode }) {
  return (
    <>
      <ArticleStyles />
      <div className="article-body">{children}</div>
    </>
  )
}

export const POST_CONTENT: Record<string, () => JSX.Element> = {

  /* ═══════════════════════════════════════════════════════════════
     Article 1: WhatsApp bot setup guide
     ═══════════════════════════════════════════════════════════════ */
  'how-to-add-whatsapp-bot-to-salla-store': () => (
    <Article>
      <p className="lead text-lg text-slate-600 leading-loose mt-0">
        تبحث عن طريقة لتفعيل <strong>بوت واتساب</strong> على متجر سلة بدون
        تعقيد؟ في هذا الدليل ستتعلم خطوة بخطوة كيف تربط مساعد ذكي بمتجرك
        ويبدأ الرد على عملائك تلقائياً خلال ٥ دقائق فقط — بدون الحاجة لأي
        خبرة برمجية.
      </p>

      <h2>لماذا تحتاج بوت واتساب لمتجر سلة؟</h2>
      <p>
        ٨٥٪ من العملاء في السوق السعودي يفضّلون التواصل عبر واتساب بدلاً من
        البريد الإلكتروني أو نموذج الاتصال. لكن الرد اليدوي على عشرات
        الرسائل يومياً مهمة مستحيلة — خاصة في أوقات الذروة أو خارج ساعات
        العمل.
      </p>
      <p>
        <strong>بوت واتساب الذكي</strong> يحل هذه المشكلة بالكامل:
      </p>
      <ul>
        <li>يرد على العملاء فوراً، حتى الساعة ٣ صباحاً</li>
        <li>يفهم استفسارات المنتجات بدقة بفضل الذكاء الاصطناعي</li>
        <li>يستعيد السلات المتروكة تلقائياً</li>
        <li>يرسل إشعارات الطلبات والشحن</li>
        <li>يتعلم من محادثاتك السابقة ويتحسن باستمرار</li>
      </ul>

      <h2>الخطوة ١: تثبيت تطبيق حياك من متجر سلة</h2>
      <p>
        ابدأ بزيارة متجر تطبيقات سلة وابحث عن <strong>"حياك"</strong>.
        اضغط على زر "تثبيت" وامنح التطبيق الصلاحيات المطلوبة (قراءة
        المنتجات، الطلبات، والعملاء). هذه الصلاحيات ضرورية ليتمكن البوت
        من الرد بدقة على استفسارات عملائك.
      </p>

      <h3>ما الصلاحيات المطلوبة بالتحديد؟</h3>
      <ul>
        <li><strong>قراءة المنتجات:</strong> ليعرف البوت كاتالوجك الفعلي</li>
        <li><strong>قراءة الطلبات:</strong> ليرد على استفسارات "أين طلبي؟"</li>
        <li><strong>قراءة العملاء:</strong> ليخاطب العميل باسمه</li>
        <li><strong>إنشاء طلبات:</strong> اختياري، لتسجيل الطلبات من المحادثة مباشرة</li>
      </ul>

      <h2>الخطوة ٢: ربط رقم واتساب الأعمال</h2>
      <p>
        بعد التثبيت، ستنتقل إلى لوحة تحكم حياك. من تبويب
        <strong> "إعدادات واتساب"</strong> أضف رقم واتساب الأعمال الخاص
        بك. ستحتاج إلى:
      </p>
      <ul>
        <li>حساب <strong>Meta Business</strong> مع رقم واتساب أعمال مفعّل</li>
        <li>الـ <code>Phone Number ID</code> من Meta Developers</li>
        <li>الـ <code>Access Token</code> الدائم (Permanent Token)</li>
      </ul>
      <p>
        إذا لم يكن لديك حساب Meta Business بعد، يمكنك إنشاؤه مجاناً من
        <a href="https://business.facebook.com" target="_blank" rel="noopener noreferrer"> business.facebook.com</a>.
        العملية تأخذ ١٥-٣٠ دقيقة وتتطلب توثيق الحساب التجاري.
      </p>

      <h2>الخطوة ٣: تخصيص شخصية البوت</h2>
      <p>
        من تبويب <strong>"ذاكرة البوت"</strong> في لوحة التحكم، يمكنك
        تخصيص:
      </p>
      <ul>
        <li><strong>اسم البوت:</strong> اختر اسماً يعكس متجرك (مثال: "نور" أو "ساعد")</li>
        <li><strong>نغمة المحادثة:</strong> رسمية، ودودة، أو مرحة</li>
        <li><strong>معلومات إضافية:</strong> سياسة الإرجاع، أوقات الشحن، طرق الدفع</li>
        <li><strong>أسئلة شائعة:</strong> أضف ردود جاهزة للأسئلة المتكررة</li>
      </ul>
      <p>
        كلما أضفت معلومات أكثر، كان البوت أذكى في الرد. ننصح بقضاء ٢٠-٣٠
        دقيقة في هذه الخطوة لأنها تحدد جودة المحادثات.
      </p>

      <h2>الخطوة ٤: تجربة البوت قبل التفعيل</h2>
      <p>
        قبل تفعيل البوت لجميع العملاء، اختبره أولاً. أرسل من رقمك الشخصي
        رسالة للبوت بأسئلة مثل:
      </p>
      <ul>
        <li>"ما هي ساعات العمل؟"</li>
        <li>"كم سعر [اسم منتج موجود في متجرك]؟"</li>
        <li>"هل التوصيل متاح لمدينة الرياض؟"</li>
        <li>"كيف يمكنني إرجاع منتج؟"</li>
      </ul>
      <p>
        راجع الردود من لوحة التحكم. إذا كان رد غير دقيق، عدّل المعلومات في
        تبويب "ذاكرة البوت" وأعد الاختبار.
      </p>

      <h2>الخطوة ٥: تفعيل البوت لجميع العملاء</h2>
      <p>
        بعد التأكد من جودة الردود، فعّل البوت من المفتاح الرئيسي في أعلى
        لوحة التحكم. سيبدأ البوت فوراً في الرد على أي رسالة جديدة تصل لرقم
        واتساب أعمال الخاص بك.
      </p>
      <p>
        <strong>نصيحة مهمة:</strong> في الأسبوع الأول راقب المحادثات من
        لوحة التحكم وتدخل يدوياً إذا رأيت رد غير مناسب. هذا يساعدك على
        تحسين البوت بسرعة.
      </p>

      <h2>أسئلة شائعة بعد التفعيل</h2>

      <h3>هل يمكنني التدخل في محادثة يردّ عليها البوت؟</h3>
      <p>
        نعم. من لوحة تحكم حياك، افتح المحادثة واضغط على "إيقاف البوت لهذه
        المحادثة"، ثم اكتب ردك بنفسك. البوت سيتوقف لهذا العميل تحديداً
        وسيستمر مع باقي العملاء.
      </p>

      <h3>ماذا يحدث إذا سأل العميل سؤال خارج معرفة البوت؟</h3>
      <p>
        البوت مبرمج ليعترف بصدق عندما لا يعرف الإجابة، ويحوّل العميل لخدمة
        العملاء البشرية. ستصلك إشعار فوري لتتدخل بنفسك.
      </p>

      <h3>هل يدعم البوت اللهجات العربية المختلفة؟</h3>
      <p>
        نعم، حياك مدرّب على اللهجات السعودية والخليجية والعربية الفصحى،
        ويرد بنفس لهجة العميل تلقائياً. للمزيد من التفاصيل، راجع
        <a href="/"> الصفحة الرئيسية</a> أو
        <a href="/blog/recover-abandoned-carts-whatsapp">مقالنا عن استرجاع السلات المتروكة</a>.
      </p>

      <h2>الخلاصة</h2>
      <p>
        ربط بوت واتساب بمتجر سلة لم يعد رفاهية — هو ضرورة لأي متجر يريد
        النمو في السوق السعودي. مع <strong>حياك</strong>، كل ما تحتاجه ٥
        دقائق لتبدأ، وأسبوع لترى الفرق في مبيعاتك ورضا عملائك.
      </p>
      <p>
        <a href="/landing">ابدأ تجربتك المجانية الآن</a> وفعّل البوت على
        متجرك خلال دقائق.
      </p>
    </Article>
  ),

  /* ═══════════════════════════════════════════════════════════════
     Article 2: Abandoned cart recovery strategies
     ═══════════════════════════════════════════════════════════════ */
  'recover-abandoned-carts-whatsapp': () => (
    <Article>
      <p className="lead text-lg text-slate-600 leading-loose mt-0">
        تعلم أن ٧٠٪ من عملائك يضيفون منتجات للسلة ثم يتركونها بدون شراء؟
        هذه ليست خسارة محتومة — مع <strong>استرجاع السلات المتروكة</strong>
        عبر واتساب، يمكنك استعادة ١٥-٣٠٪ منهم وزيادة مبيعاتك بدون أي
        تكلفة إعلانية إضافية.
      </p>

      <h2>لماذا يترك العملاء سلاتهم؟</h2>
      <p>
        قبل ما نتكلم عن الحلول، نفهم المشكلة. الأسباب الشائعة لترك السلات
        في السوق السعودي:
      </p>
      <ul>
        <li><strong>تكلفة شحن مفاجئة (٤٨٪):</strong> العميل يصدم بسعر شحن لم يتوقعه</li>
        <li><strong>إنشاء حساب إجباري (٢٤٪):</strong> العميل لا يريد عملية تسجيل طويلة</li>
        <li><strong>مقارنة الأسعار (١٨٪):</strong> العميل يتركها ليبحث في متاجر أخرى</li>
        <li><strong>تعقيد عملية الدفع (١٢٪):</strong> طرق دفع غير مناسبة أو خطوات كثيرة</li>
        <li><strong>تشتت بسيط (٢٢٪):</strong> رنين الهاتف، الأطفال، الخروج من المنزل</li>
      </ul>
      <p>
        الفئة الأخيرة — التشتت — هي الأسهل في الاسترجاع. هذا العميل كان
        قاب قوسين من الشراء.
      </p>

      <h2>الاستراتيجية ١: رسالة تذكير سريعة (خلال ٣٠ دقيقة)</h2>
      <p>
        التوقيت كل شيء. رسالة بعد ٣٠ دقيقة تستهدف العميل وهو لا يزال يفكر
        في الشراء. مثال:
      </p>
      <blockquote>
        "أهلاً [اسم العميل] 👋، لاحظنا إن في منتجات بانتظارك في سلتك. حابب
        نكمل الطلب أو محتاج مساعدة في حاجة؟"
      </blockquote>
      <p>
        مع <strong>حياك</strong>، هذه الرسالة تُرسل تلقائياً عبر واتساب
        لكل عميل ترك سلة، بدون أي تدخل منك.
      </p>

      <h2>الاستراتيجية ٢: عرض خصم محدود (بعد ٢-٤ ساعات)</h2>
      <p>
        إذا لم يكمل العميل الطلب بعد التذكير الأول، أرسل عرض مغري بعد ٢-٤
        ساعات:
      </p>
      <blockquote>
        "خصم ١٠٪ صلاحيته ٢٤ ساعة فقط على طلبك ✨ استخدم كود: WELCOME10"
      </blockquote>
      <p>
        هذا يخلق إحساس <strong>الإلحاح</strong> ويعطي العميل سبب إضافي
        للإكمال. اضبط نسبة الخصم بحيث تكون مربحة لك بعد حساب التكلفة.
      </p>

      <h2>الاستراتيجية ٣: شحن مجاني كحافز</h2>
      <p>
        ٤٨٪ من السلات تُترك بسبب الشحن. إذا أعطيت شحن مجاني، تكسب نصف
        العملاء المتروكين فوراً:
      </p>
      <blockquote>
        "أكمل طلبك الآن واحصل على شحن مجاني لجميع مدن المملكة 🚚"
      </blockquote>
      <p>
        هذه الاستراتيجية فعالة جداً للطلبات فوق ١٥٠ ريال — هامش ربحك يغطي
        تكلفة الشحن بسهولة.
      </p>

      <h2>الاستراتيجية ٤: عرض المنتجات ذات الصلة</h2>
      <p>
        أحياناً العميل تركها لأن المنتج لم يكن مناسب تماماً. اعرض بدائل:
      </p>
      <blockquote>
        "لقينا منتجات شبيهة بالـ[منتج المتروك] ممكن تعجبك: [قائمة المنتجات]"
      </blockquote>

      <h2>الاستراتيجية ٥: مراجعات وضمانات</h2>
      <p>
        إذا كان العميل متردد، طمأنه:
      </p>
      <blockquote>
        "هذا المنتج حصل على ١٢٧ تقييم بـ ⭐⭐⭐⭐⭐ ومدعوم بضمان استرجاع
        ١٤ يوم بدون أسئلة."
      </blockquote>

      <h2>الاستراتيجية ٦: السؤال المباشر "إيش اللي يمنعك؟"</h2>
      <p>
        أحياناً المباشرة أفضل من العروض. اسأل العميل بصراحة:
      </p>
      <blockquote>
        "حابب نعرف، إيه اللي خلاك ما تكمل الطلب؟ سعر؟ شحن؟ مقاس؟ أي رد
        منك يساعدنا نتحسن ❤️"
      </blockquote>
      <p>
        الإجابات اللي بتجي على هذا السؤال تعطيك insights ذهبية لتحسين
        تجربة الشراء عموماً.
      </p>

      <h2>الاستراتيجية ٧: رسالة من المدير شخصياً</h2>
      <p>
        لمسة شخصية تصنع الفرق. للطلبات الكبيرة (فوق ٥٠٠ ريال) أرسل رسالة
        من المؤسس أو المدير:
      </p>
      <blockquote>
        "السلام عليكم، أنا [اسمك] مؤسس متجر [اسم المتجر]. لاحظت إنك تركت
        سلة بمنتجات قيّمة. لو في أي حاجة محتاج مساعدة فيها، أنا متاح
        مباشرة."
      </blockquote>

      <h2>الاستراتيجية ٨: تذكير ثاني بعد ٢٤ ساعة</h2>
      <p>
        إذا لم يستجب العميل، رسالة أخيرة بعد ٢٤ ساعة:
      </p>
      <blockquote>
        "آخر تذكير 🔔 منتجاتك لا تزال في سلتك. هل نحتفظ بها لك يوم آخر أم
        نلغي الحجز؟"
      </blockquote>
      <p>
        كلمة "إلغاء" تخلق خوف الفقدان وقد تدفعه للإكمال.
      </p>

      <h2>الاستراتيجية ٩: تقسيم الجمهور حسب القيمة</h2>
      <p>
        ليس كل العملاء سواء. قسّم العملاء المتروكين:
      </p>
      <ul>
        <li><strong>عملاء VIP (طلباتهم السابقة فوق ١٠٠٠ ريال):</strong> أرسل عرض شخصي حصري</li>
        <li><strong>عملاء جدد:</strong> ركز على بناء الثقة (تقييمات، ضمانات)</li>
        <li><strong>عملاء متكررون:</strong> ذكّرهم بنقاط الولاء أو الخصومات</li>
      </ul>

      <h2>الاستراتيجية ١٠: قياس وتحسين باستمرار</h2>
      <p>
        راقب من لوحة تحكم <strong>حياك</strong>:
      </p>
      <ul>
        <li>نسبة الاسترجاع لكل استراتيجية</li>
        <li>أفضل وقت لإرسال الرسائل (حسب جمهورك)</li>
        <li>أكثر الأسباب لترك السلات</li>
        <li>متوسط قيمة السلة المسترجعة</li>
      </ul>
      <p>
        كرر ما يعمل، أوقف ما لا يعمل، واختبر استراتيجيات جديدة كل أسبوعين.
      </p>

      <h2>كيف تفعّل استرجاع السلات في حياك؟</h2>
      <p>
        مع <strong>حياك</strong>، كل ما سبق مفعّل تلقائياً بدون كتابة سطر
        واحد:
      </p>
      <ol>
        <li>اربط متجر سلة (راجع <a href="/blog/how-to-add-whatsapp-bot-to-salla-store">دليل ربط بوت واتساب بمتجر سلة</a>)</li>
        <li>فعّل ميزة "استرجاع السلات المتروكة" من الإعدادات</li>
        <li>خصص رسائل التذكير حسب نغمة متجرك</li>
        <li>اضبط التوقيتات (٣٠ دقيقة، ٢-٤ ساعات، ٢٤ ساعة)</li>
        <li>راقب النتائج من لوحة التحكم</li>
      </ol>

      <h2>الخلاصة</h2>
      <p>
        السلات المتروكة ليست عقبة — هي فرصة. ٧٠٪ من العملاء اللي يتركون
        السلة قابلين للاسترجاع بالاستراتيجية الصحيحة. مع <strong>حياك</strong>،
        تطبيق هذه الاستراتيجيات يأخذ دقائق، والنتيجة زيادة مبيعات
        ١٥-٣٠٪ خلال شهر واحد.
      </p>
      <p>
        <a href="/landing">ابدأ تجربتك المجانية</a> وفعّل استرجاع السلات
        المتروكة على متجرك الآن.
      </p>
    </Article>
  ),

}
