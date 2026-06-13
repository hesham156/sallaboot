import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'

export default function TermsOfService() {
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
            <img src="/uploads/logo.png" style={{ maxWidth: '100%', height: 'auto', width: '140px' }}/>
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
            اتفاقية الاستخدام
          </span>
          <h1 className="text-3xl sm:text-4xl font-black text-slate-900 leading-tight">
            شروط الخدمة لـ <span className="text-gradient">حياك</span>
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
              <span className="text-teal-500 text-xl">📋</span> ١. قبول الشروط
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed">
              باستخدامك أو تسجيلك في منصة <b>حياك</b>، فإنك تقر وتوافق على الالتزام بشروط الخدمة هذه. إذا كنت لا توافق على هذه الشروط كلياً أو جزئياً، فيجب عليك عدم استخدام المنصة أو أي من خدماتها المتاحة.
            </p>
          </div>

          {/* Card 2 */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)]">
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">⚙️</span> ٢. وصف الخدمة
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed">
              حياك هي منصة برمجيات كخدمة (SaaS) تقدم حلول الذكاء الاصطناعي لمتاجر سلة، بما في ذلك روبوتات محادثة تفاعلية للرد الفوري على أسئلة العملاء، وتوفير حاسبات تسعير متقدمة للمنتجات المخصصة، واستعادة السلات المتروكة وتأكيد الطلبات تلقائياً. يحق لنا تعديل، تحديث، أو إيقاف أي جزء من الخدمة في أي وقت لغرض التطوير أو الصيانة.
            </p>
          </div>

          {/* Card 3 */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)]">
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">👤</span> ٣. حساب المستخدم والتكامل
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed mb-3">
              للاستفادة من خدمات حياك:
            </p>
            <ul className="list-disc list-inside space-y-2.5 text-slate-600 text-sm sm:text-base mr-2">
              <li>يجب أن تكون صاحب متجر إلكتروني نشط وموثق على منصة سلة (Salla).</li>
              <li>أنت مسؤول بالكامل عن الحفاظ على سرية بيانات تسجيل دخولك إلى لوحة التحكم وأي نشاط يحدث تحت حسابك.</li>
              <li>أنت تفوض حياك بشكل كامل للاتصال بمتجرك عبر واجهة برمجة التطبيقات (API) الخاصة بسلة لقراءة المنتجات، وتحديث الأسعار، وتلقي تنبيهات الطلبات لضمان عمل الخدمة بشكل صحيح.</li>
            </ul>
          </div>

          {/* Card 4 */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)]">
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">💳</span> ٤. الاشتراكات والدفع والتجديد
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed mb-3">
              تخضع الخدمة لخطط اشتراك دورية (شهرية أو سنوية) موضحة في لوحة التحكم:
            </p>
            <ul className="list-disc list-inside space-y-2.5 text-slate-600 text-sm sm:text-base mr-2">
              <li>يتم دفع رسوم الاشتراك مقدماً وتجدد تلقائياً ما لم يتم إلغاء الاشتراك من قبلك قبل تاريخ التجديد.</li>
              <li>جميع الرسوم المدفوعة غير قابلة للاسترداد بعد تفعيل الاشتراك الفعلي، نظراً للتكاليف المترتبة على حجز موارد الخوادم والذكاء الاصطناعي لمتجرك.</li>
              <li>يحق لنا مراجعة وتعديل أسعار الباقات مع إخطار المشتركين مسبقاً بفترة لا تقل عن ٣٠ يوماً.</li>
            </ul>
          </div>

          {/* Card 5 */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)]">
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">🚫</span> ٥. الاستخدام المحظور
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed mb-3">
              أنت توافق على استخدام حياك بطريقة تتوافق مع الأنظمة والقوانين المعمول بها. يمنع منعاً باتاً استخدام المنصة في:
            </p>
            <ul className="list-disc list-inside space-y-2.5 text-slate-600 text-sm sm:text-base mr-2">
              <li>الترويج أو بيع منتجات غير قانونية أو مخالفة للشريعة الإسلامية والأنظمة المحلية.</li>
              <li>إرسال رسائل سبام أو مضايقة أو محتوى مضلل وغير لائق للعملاء عبر البوت.</li>
              <li>محاولة فك تشفير، أو اختراق، أو إلحاق الضرر بالبنية التحتية البرمجية لحياك.</li>
            </ul>
          </div>

          {/* Card 6 */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)]">
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">🔒</span> ٦. مسؤولية المحتوى والذكاء الاصطناعي
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed">
              يعتمد أداء المساعد الذكي على المعلومات التي تقدمها في لوحة التحكم (المنتجات، شروط الخدمة، وإعدادات التدريب). على الرغم من أننا نسعى لتقديم أدق النتائج وأحدث تقنيات الفهم اللغوي، فإن حياك لا يتحمل المسؤولية عن أي إجابات أو معلومات خاطئة أو غير دقيقة يولدها البوت للعملاء بشكل تلقائي. يقع على عاتق مدير المتجر مراجعة وتعديل قاعدة تدريب البوت وتصحيحها لضمان مطابقتها لسياسة متجره.
            </p>
          </div>

          {/* Card 7 */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)]">
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">⚡</span> ٧. حدود المسؤولية
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed">
              إلى أقصى حد يسمح به القانون المعمول به، لا يتحمل حياك بأي حال من الأحوال المسؤولية عن أي خسائر مالية، أو خسارة في الأرباح، أو توقف للمتجر، أو أضرار ناتجة عن انقطاع مؤقت في الخدمة، أو مشاكل في الاتصال بخوادم سلة، أو فقدان للبيانات نتيجة لاستخدامك للمنصة.
            </p>
          </div>

          {/* Card 8 */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)]">
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">📞</span> ٨. التواصل والاستفسارات
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed">
              لأي استفسار بخصوص شروط الخدمة هذه، يرجى التواصل مع فريق الدعم القانوني والفني عبر البريد الإلكتروني التالي:
              <a href="mailto:support@7ayak.app" className="text-teal-600 hover:underline font-bold dir-ltr inline-block mx-1.5">support@7ayak.app</a>
            </p>
          </div>
        </motion.div>
      </div>
    </div>
  )
}
