import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'

export default function DataDeletion() {
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
            تنظيم وحذف البيانات
          </span>
          <h1 className="text-3xl sm:text-4xl font-black text-slate-900 leading-tight">
            تعليمات حذف بيانات <span className="text-gradient">المستخدمين</span>
          </h1>
          <p className="text-slate-500 text-sm mt-3">نضمن لك حقك الكامل في حذف بياناتك بشكل آمن ونهائي في أي وقت.</p>
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
          {/* Intro Card */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)]">
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-3 flex items-center gap-2">
              <span className="text-teal-500 text-xl">ℹ️</span> نظرة عامة
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed">
              وفقاً لقوانين حماية البيانات العامة وسياسات المطورين (مثل سياسات Meta/Facebook)، يحق لأي مستخدم يتفاعل مع تطبيق <b>حياك</b> طلب حذف بياناته الشخصية المخزنة لدينا. نوضح في هذه الصفحة الإرشادات اللازمة لأصحاب المتاجر وعملائهم لإتمام هذه العملية بكل سهولة.
            </p>
          </div>

          {/* Owner Instructions Card */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)] relative overflow-hidden">
            <div className="absolute top-0 left-0 w-2 h-full bg-gradient-to-b from-teal-500 to-cyan-500" />
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">🛍️</span> أولاً: تعليمات أصحاب المتاجر (Store Owners)
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed mb-4">
              إذا كنت تملك متجراً إلكترونياً مشتركاً في حياك وترغب في إلغاء حسابك وحذف جميع بيانات متجرك نهائياً، يمكنك القيام بذلك عبر إحدى الطرق التالية:
            </p>

            <div className="space-y-4">
              <div className="flex gap-3 items-start bg-slate-50 p-4 rounded-2xl">
                <span className="w-6 h-6 rounded-full bg-teal-100 text-teal-700 text-xs font-black flex items-center justify-center flex-shrink-0 mt-0.5">١</span>
                <div>
                  <h3 className="font-bold text-slate-900 text-sm sm:text-base">حذف التطبيق التلقائي من متجر سلة (موصى به)</h3>
                  <p className="text-slate-600 text-xs sm:text-sm mt-1 leading-relaxed">
                    توجه إلى لوحة تحكم متجرك في سلة، ثم اذهب إلى "التطبيقات المثبتة"، وابحث عن تطبيق "حياك" وقم بعملية إلغاء التثبيت (Uninstall). عند القيام بذلك، يرسل نظام سلة تنبيهاً فورياً (Webhook) لخوادمنا، ويقوم نظامنا تلقائياً بحذف جميع بيانات متجرك وقاعدة التدريب والمنتجات المسحوبة والرموز السرية نهائياً من قاعدة البيانات.
                  </p>
                </div>
              </div>

              <div className="flex gap-3 items-start bg-slate-50 p-4 rounded-2xl">
                <span className="w-6 h-6 rounded-full bg-teal-100 text-teal-700 text-xs font-black flex items-center justify-center flex-shrink-0 mt-0.5">٢</span>
                <div>
                  <h3 className="font-bold text-slate-900 text-sm sm:text-base">الطلب المباشر عبر الدعم الفني</h3>
                  <p className="text-slate-600 text-xs sm:text-sm mt-1 leading-relaxed">
                    يمكنك مراسلتنا من البريد الإلكتروني الخاص بمالك المتجر المسجل لدينا إلى البريد الإلكتروني <a href="mailto:support@sallaboot.com" className="text-teal-600 hover:underline font-bold">support@sallaboot.com</a> بعنوان "طلب حذف حساب المتجر والبيانات"، وسيقوم فريق الدعم بحذف الحساب وكافة البيانات المرتبطة به خلال ٤٨ ساعة وإشعارك بالتأكيد.
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Customer Instructions Card */}
          <div className="bg-white border border-slate-100 rounded-3xl p-7 sm:p-8 shadow-[0_4px_24px_rgba(15,23,42,0.02)] relative overflow-hidden">
            <div className="absolute top-0 left-0 w-2 h-full bg-gradient-to-b from-cyan-500 to-teal-500" />
            <h2 className="text-lg sm:text-xl font-black text-slate-900 mb-4 flex items-center gap-2">
              <span className="text-teal-500 text-xl">👥</span> ثانياً: تعليمات عملاء المتاجر (Store Customers)
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed mb-4">
              إذا كنت عميلاً أو زائراً قمت بالتواصل مع المساعد الذكي (حياك) في أحد المتاجر الإلكترونية وترغب في مسح سجل محادثاتك أو بيانات التواصل الخاصة بك المخزنة لدى البوت:
            </p>

            <div className="space-y-4">
              <div className="flex gap-3 items-start bg-slate-50 p-4 rounded-2xl">
                <span className="w-6 h-6 rounded-full bg-cyan-100 text-cyan-700 text-xs font-black flex items-center justify-center flex-shrink-0 mt-0.5">١</span>
                <div>
                  <h3 className="font-bold text-slate-900 text-sm sm:text-base">التواصل مع إدارة المتجر المعني</h3>
                  <p className="text-slate-600 text-xs sm:text-sm mt-1 leading-relaxed">
                    يحق لك مطالبة إدارة المتجر الذي اشتريت منه بحذف بياناتك. يمكن لمدير المتجر من خلال لوحة تحكم حياك مسح سجل أي محادثة أو طلب خاص بزبائنهم بضغطة زر.
                  </p>
                </div>
              </div>

              <div className="flex gap-3 items-start bg-slate-50 p-4 rounded-2xl">
                <span className="w-6 h-6 rounded-full bg-cyan-100 text-cyan-700 text-xs font-black flex items-center justify-center flex-shrink-0 mt-0.5">٢</span>
                <div>
                  <h3 className="font-bold text-slate-900 text-sm sm:text-base">التواصل معنا مباشرة</h3>
                  <p className="text-slate-600 text-xs sm:text-sm mt-1 leading-relaxed">
                    إذا تعذر التواصل مع المتجر، يمكنك مراسلتنا مباشرة على <a href="mailto:support@sallaboot.com" className="text-teal-600 hover:underline font-bold">support@sallaboot.com</a> مع تزويدنا برقم هاتفك أو معرف المستخدم الذي تواصلت به واسم المتجر. سنقوم بالتحقق من الطلب ومسح سجل محادثاتك تماماً من خوادمنا خلال فترة أقصاها ١٤ يوماً عمل.
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Meta Compliance Alert */}
          <div className="bg-emerald-50 border border-emerald-100 rounded-3xl p-6 shadow-sm">
            <h3 className="font-bold text-emerald-800 text-base mb-2 flex items-center gap-1.5">
              <span>✅</span> توافق كامل مع معايير المنصات العالمية
            </h3>
            <p className="text-emerald-700 text-xs sm:text-sm leading-relaxed">
              تتوافق آلية حذف البيانات الخاصة بنا مع شروط استخدام واجهات مطوري فيسبوك وتليجرام وواتساب، لضمان حماية الخصوصية وتوفير خيار الحذف الكامل والفوري بمجرد إلغاء تثبيت التطبيقات أو استلام طلب الحذف الفني.
            </p>
          </div>
        </motion.div>
      </div>
    </div>
  )
}
