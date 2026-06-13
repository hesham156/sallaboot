import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'

export default function PrivacyPolicy() {
  const navigate = useNavigate()

  return (
    <div dir="rtl" className="min-h-screen bg-slate-50/50 text-slate-800 font-sans pb-20 overflow-x-hidden">
      {/* Background Glows */}
      <div className="absolute top-[-6rem] right-[-6rem] w-[34rem] h-[34rem] bg-teal-300/20 rounded-full blur-[130px] pointer-events-none" />
      <div className="absolute top-[10rem] left-[-8rem] w-[30rem] h-[30rem] bg-cyan-300/15 rounded-full blur-[130px] pointer-events-none" />

      {/* Header */}
      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-slate-100">
        <nav className="max-w-5xl mx-auto px-6 h-16 flex items-center justify-between">
          <a href="/" className="flex items-center gap-2.5">
            <img src="/uploads/logo.png" className="h-9"/>
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

      {/* Title Hero */}
      <div className="max-w-4xl mx-auto px-6 pt-16 pb-10 text-center">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          <span className="inline-block text-xs font-bold text-teal-600 bg-teal-50 rounded-full px-3.5 py-1.5 mb-4">
            الخصوصية والأمان
          </span>
          <h1 className="text-3xl sm:text-4xl font-black text-slate-900 leading-tight">
            سياسة الخصوصية لـ <span className="text-gradient">حياك</span>
          </h1>
          <p className="text-slate-500 text-sm mt-3">آخر تحديث: ٦ يونيو ٢٠٢٦</p>
        </motion.div>
      </div>

      {/* Content Container */}
      <div className="max-w-4xl mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1 }}
          className="space-y-6"
        >
          {/* Card 1 */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)]">
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">📋</span> ١. مقدمة
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed">
              نهتم في منصة <b>حياك</b> (المساعد الذكي لمتاجر سلة) بخصوصية بياناتك وبيانات عملائك بشكل قصوى. توضح هذه السياسة كيف نجمع، ونعالج، ونحمي المعلومات والبيانات عند استخدامك لمنصتنا وتكاملها مع متجرك الإلكتروني. باستخدامك لحياك، فإنك توافق على الممارسات الموضحة في هذه الصفحة.
            </p>
          </div>

          {/* Card 2 */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)]">
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">🔍</span> ٢. البيانات التي نجمعها
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed mb-4">
              لكي نتمكن من تشغيل المساعد الذكي وربطه بمتجرك، نقوم بجمع ومعالجة البيانات التالية:
            </p>
            <ul className="list-disc list-inside space-y-2.5 text-slate-600 text-sm sm:text-base mr-2">
              <li><b>بيانات المتجر:</b> اسم المتجر، الشعار، قائمة المنتجات، الأسعار، وحالة المخزون، لتمكين البوت من إجابة العملاء بدقة.</li>
              <li><b>بيانات المحادثات:</b> الرسائل المتبادلة بين عملائك والبوت، والأسئلة الشائعة، لتطوير أداء الذكاء الاصطناعي وتقديم خدمة التسعير والطلب الفوري.</li>
              <li><b>بيانات الطلبات:</b> تفاصيل السلات المتروكة وبيانات الطلب الجديد (مثل قيمة الطلب والمنتجات) لمساعدتك في استرجاع المبيعات وتأكيد الطلبات.</li>
              <li><b>بيانات الحساب:</b> البريد الإلكتروني للمدير، واسم المستخدم، وتفاصيل الدخول الخاصة بلوحة تحكم حياك لتوثيق الحساب.</li>
            </ul>
          </div>

          {/* Card 3 */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)]">
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">⚙️</span> ٣. كيف نستخدم بياناتك
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed mb-4">
              نحن نستخدم البيانات التي نجمعها للأغراض التالية فقط:
            </p>
            <ul className="list-disc list-inside space-y-2.5 text-slate-600 text-sm sm:text-base mr-2">
              <li>توفير وتفعيل محادثات المساعد الذكي على متجرك للرد الفوري على العملاء.</li>
              <li>حساب أسعار الطباعة والخدمات بناءً على مدخلاتك المخصصة وتحديثها بشكل فوري.</li>
              <li>متابعة السلات المتروكة وإرسال تذكيرات ذكية للعملاء لإتمام الدفع.</li>
              <li>تحسين جودة الخدمة من خلال تدريب وتحديث نموذج الذكاء الاصطناعي الخاص بمتجرك استناداً إلى ملاحظاتك.</li>
              <li>إرسال تنبيهات وتحديثات هامة تتعلق بحسابك أو فواتير الخدمة.</li>
            </ul>
          </div>

          {/* Card 4 */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)]">
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">🔒</span> ٤. حماية وأمن البيانات
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed">
              نلتزم بحماية بياناتك بأعلى معايير الأمان التقنية والمعلوماتية. نستخدم تقنيات التشفير المتقدمة (SSL/TLS) لحماية نقل البيانات، ويتم تخزين معلوماتك في قواعد بيانات سحابية آمنة ومحمية بجدران نارية ومراقبة مستمرة لمنع أي وصول غير مصرح به.
            </p>
          </div>

          {/* Card 5 */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)]">
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">🔄</span> ٥. مشاركة البيانات مع أطراف ثالثة
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed">
              <b>لا نقوم ببيع أو تأجير أو مشاركة</b> أي بيانات خاصة بمتجرك أو عملائك مع أي جهات خارجية لأغراض تسويقية أو تجارية مطلقاً. قد تتم مشاركة أجزاء من نصوص المحادثات بشكل آمن ومشفر مع مزودي خدمات الذكاء الاصطناعي (مثل OpenAI أو Google Cloud) لتوليد ردود البوت، ويتم ذلك وفقاً لسياسات خصوصية صارمة تمنعهم من استخدام بياناتك لأغراضهم الخاصة.
            </p>
          </div>

          {/* Card 6 */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)]">
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">👤</span> ٦. حقوقك والتحكم في البيانات
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed mb-3">
              نحن نؤمن بحقك الكامل في التحكم ببياناتك. يحق لك في أي وقت:
            </p>
            <ul className="list-disc list-inside space-y-2.5 text-slate-600 text-sm sm:text-base mr-2">
              <li>الاطلاع على البيانات المخزنة لدينا أو تصديرها.</li>
              <li>طلب تعديل أو تصحيح أي معلومات خاطئة في حسابك.</li>
              <li>طلب <b>حذف بياناتك بالكامل وبشكل نهائي</b> من خوادمنا. (لمعرفة الخطوات يرجى زيارة صفحة <a href="/data-deletion" className="text-teal-600 hover:underline font-bold">تعليمات حذف البيانات</a>).</li>
            </ul>
          </div>

          {/* Card 7 */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)]">
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">📞</span> ٧. اتصل بنا
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed">
              إذا كانت لديك أي أسئلة أو استفسارات حول سياسة الخصوصية هذه أو كيفية معالجة بياناتك، لا تتردد في التواصل معنا عبر البريد الإلكتروني:
              <a href="mailto:support@sallaboot.com" className="text-teal-600 hover:underline font-bold dir-ltr inline-block mx-1.5">support@sallaboot.com</a>
            </p>
          </div>
        </motion.div>
      </div>
    </div>
  )
}
