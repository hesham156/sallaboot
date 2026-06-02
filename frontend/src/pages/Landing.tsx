import { useNavigate } from 'react-router-dom'
import { getToken, getIsSuper, getStoreId } from '../api'

function Icon({ paths, size = 20, className = '' }: {
  paths: string | string[]
  size?: number
  className?: string
}) {
  const arr = Array.isArray(paths) ? paths : [paths]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth={1.8}
      strokeLinecap="round" strokeLinejoin="round" className={className}>
      {arr.map((d, i) => <path key={i} d={d} />)}
    </svg>
  )
}

const FEATURES = [
  {
    icon: ['M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z'],
    title: 'دردشة ذكية فورية',
    desc: 'بوت AI يرد على عملاء متجرك تلقائياً على مدار الساعة، يفهم أسئلتهم ويجيب عليها بدقة عالية بالعربية.',
    gradient: 'from-blue-500/15 to-cyan-500/10',
    border: 'border-blue-500/20',
    iconBg: 'bg-blue-500/15',
    iconColor: 'text-blue-400',
  },
  {
    icon: ['M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4'],
    title: 'مزامنة المنتجات تلقائياً',
    desc: 'البوت يتعلم منتجاتك وأسعارك وتفاصيلها مباشرةً من متجر سلة، ويحدّث نفسه تلقائياً عند أي تغيير.',
    gradient: 'from-emerald-500/15 to-teal-500/10',
    border: 'border-emerald-500/20',
    iconBg: 'bg-emerald-500/15',
    iconColor: 'text-emerald-400',
  },
  {
    icon: ['M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z'],
    title: 'تحليلات وإحصائيات',
    desc: 'راقب أداء البوت، أكثر الأسئلة تكراراً، معدلات التحويل، والمحادثات الناجحة من لوحة تحكم واحدة.',
    gradient: 'from-violet-500/15 to-purple-500/10',
    border: 'border-violet-500/20',
    iconBg: 'bg-violet-500/15',
    iconColor: 'text-violet-400',
  },
  {
    icon: ['M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z'],
    title: 'تدريب مخصص للمتجر',
    desc: 'علّم البوت شخصية متجرك وأسلوبك وسياساتك الخاصة، فيرد بنفس روح علامتك التجارية.',
    gradient: 'from-amber-500/15 to-orange-500/10',
    border: 'border-amber-500/20',
    iconBg: 'bg-amber-500/15',
    iconColor: 'text-amber-400',
  },
  {
    icon: ['M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z'],
    title: 'إدارة الطلبات والسلات',
    desc: 'البوت يساعد عملاءك في تتبع طلباتهم، ويُذكّر بالسلات المتروكة ويحوّلها لمبيعات حقيقية.',
    gradient: 'from-rose-500/15 to-pink-500/10',
    border: 'border-rose-500/20',
    iconBg: 'bg-rose-500/15',
    iconColor: 'text-rose-400',
  },
  {
    icon: ['M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z'],
    title: 'أمان وخصوصية تامة',
    desc: 'بيانات متجرك محمية بتشفير كامل، كل متجر معزول تماماً عن الآخرين في بيئة مستقلة.',
    gradient: 'from-slate-500/15 to-zinc-500/10',
    border: 'border-slate-500/20',
    iconBg: 'bg-slate-500/15',
    iconColor: 'text-slate-400',
  },
]

const STATS = [
  { value: '24/7', label: 'متاح على مدار الساعة' },
  { value: '< 2ث', label: 'متوسط وقت الرد' },
  { value: '٩٥٪', label: 'دقة الإجابات' },
  { value: 'سلة', label: 'متكامل مع منصة' },
]

const HOW_STEPS = [
  {
    num: '١',
    title: 'سجّل متجرك',
    desc: 'اربط متجر سلة الخاص بك بـ Access Token بخطوة واحدة بسيطة.',
    color: 'text-blue-400',
    ring: 'ring-blue-500/30 bg-blue-500/10',
  },
  {
    num: '٢',
    title: 'اضبط البوت',
    desc: 'خصّص شخصية البوت وأضف معلومات متجرك ودرّبه على أسئلة عملاءك.',
    color: 'text-violet-400',
    ring: 'ring-violet-500/30 bg-violet-500/10',
  },
  {
    num: '٣',
    title: 'ابدأ الاستقبال',
    desc: 'فعّل البوت وابدأ استقبال رسائل عملاءك تلقائياً بدون تدخل منك.',
    color: 'text-emerald-400',
    ring: 'ring-emerald-500/30 bg-emerald-500/10',
  },
]

export default function Landing() {
  const navigate = useNavigate()

  function handleCTA() {
    const token = getToken()
    if (!token) { navigate('/login'); return }
    navigate(getIsSuper() ? '/' : `/store/${getStoreId()}`)
  }

  return (
    <div className="min-h-screen bg-background text-foreground" dir="rtl">

      {/* ══════════════ NAV ══════════════ */}
      <nav className="sticky top-0 z-50 border-b border-divider bg-background/80 backdrop-blur-xl">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          {/* Logo */}
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-teal-500 to-cyan-600 flex items-center justify-center shadow-lg shadow-teal-500/30">
              <Icon paths="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" size={17} className="text-white" />
            </div>
            <span className="font-black text-lg text-foreground">سلّابوت</span>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            <button
              onClick={handleCTA}
              className="px-4 py-2 rounded-xl text-sm font-semibold text-slate-400 hover:text-foreground transition-colors"
            >
              تسجيل الدخول
            </button>
            <button
              onClick={handleCTA}
              className="px-4 py-2 rounded-xl text-sm font-bold bg-gradient-to-l from-teal-500 to-cyan-500 text-white shadow-lg shadow-teal-500/25 hover:shadow-teal-500/40 hover:scale-[1.02] transition-all"
            >
              ابدأ مجاناً
            </button>
          </div>
        </div>
      </nav>

      {/* ══════════════ HERO ══════════════ */}
      <section className="relative overflow-hidden py-24 px-6">
        {/* Background glows */}
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[700px] h-[400px] bg-teal-500/8 rounded-full blur-[100px]" />
          <div className="absolute top-20 right-0 w-[300px] h-[300px] bg-cyan-500/6 rounded-full blur-[80px]" />
          <div className="absolute bottom-0 left-0 w-[300px] h-[300px] bg-violet-500/6 rounded-full blur-[80px]" />
        </div>

        <div className="relative max-w-4xl mx-auto text-center space-y-8">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full border border-teal-500/25 bg-teal-500/8 text-teal-400 text-sm font-semibold">
            <span className="w-2 h-2 bg-teal-400 rounded-full animate-pulse" />
            مدعوم بالذكاء الاصطناعي · متكامل مع سلة
          </div>

          {/* Headline */}
          <h1 className="text-5xl md:text-6xl font-black leading-tight">
            بوت ذكي يبيع
            <br />
            <span className="bg-gradient-to-l from-teal-400 to-cyan-400 bg-clip-text text-transparent">
              بدلاً عنك
            </span>
          </h1>

          {/* Sub */}
          <p className="text-xl text-slate-400 leading-relaxed max-w-2xl mx-auto">
            حوّل زوار متجرك على سلة إلى عملاء حقيقيين. بوت AI يرد على كل سؤال،
            يشرح كل منتج، ويتابع كل طلب — على مدار الساعة بدون توقف.
          </p>

          {/* CTA buttons */}
          <div className="flex items-center justify-center gap-3 flex-wrap">
            <button
              onClick={handleCTA}
              className="flex items-center gap-2 px-7 py-3.5 rounded-2xl font-bold text-base bg-gradient-to-l from-teal-500 to-cyan-500 text-white shadow-xl shadow-teal-500/30 hover:shadow-teal-500/50 hover:scale-[1.03] transition-all"
            >
              <Icon paths="M13 10V3L4 14h7v7l9-11h-7z" size={18} />
              ابدأ مجاناً الآن
            </button>
            <button
              onClick={handleCTA}
              className="flex items-center gap-2 px-7 py-3.5 rounded-2xl font-bold text-base border border-divider bg-content1 text-default-600 hover:text-foreground hover:border-slate-500 transition-all"
            >
              <Icon paths="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" size={18} />
              عرض تجريبي
            </button>
          </div>

          {/* Trust line */}
          <p className="text-xs text-slate-600">
            لا يلزم بطاقة ائتمانية · إعداد في أقل من دقيقتين
          </p>
        </div>
      </section>

      {/* ══════════════ STATS ══════════════ */}
      <section className="py-12 px-6 border-y border-divider bg-content1/40">
        <div className="max-w-4xl mx-auto grid grid-cols-2 md:grid-cols-4 gap-6">
          {STATS.map(s => (
            <div key={s.value} className="text-center">
              <p className="text-3xl font-black text-foreground mb-1">{s.value}</p>
              <p className="text-xs text-slate-500 font-medium">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ══════════════ FEATURES ══════════════ */}
      <section className="py-24 px-6">
        <div className="max-w-6xl mx-auto space-y-14">
          {/* Section header */}
          <div className="text-center space-y-3">
            <p className="text-teal-400 font-semibold text-sm uppercase tracking-widest">المزايا</p>
            <h2 className="text-3xl md:text-4xl font-black">كل ما يحتاجه متجرك في مكان واحد</h2>
            <p className="text-slate-400 max-w-xl mx-auto">
              منظومة متكاملة من الأدوات الذكية مصممة خصيصاً لمتاجر سلة
            </p>
          </div>

          {/* Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {FEATURES.map(f => (
              <div
                key={f.title}
                className={`relative overflow-hidden rounded-2xl bg-content1 border ${f.border} p-6 hover:scale-[1.02] transition-all duration-300`}
              >
                <div className={`absolute inset-0 bg-gradient-to-br ${f.gradient} pointer-events-none`} />
                <div className="relative space-y-4">
                  <div className={`w-11 h-11 ${f.iconBg} rounded-xl flex items-center justify-center ${f.iconColor}`}>
                    <Icon paths={f.icon} size={20} />
                  </div>
                  <div>
                    <h3 className="font-bold text-base text-foreground mb-2">{f.title}</h3>
                    <p className="text-sm text-slate-400 leading-relaxed">{f.desc}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ══════════════ HOW IT WORKS ══════════════ */}
      <section className="py-24 px-6 bg-content1/30 border-y border-divider">
        <div className="max-w-4xl mx-auto space-y-14">
          <div className="text-center space-y-3">
            <p className="text-teal-400 font-semibold text-sm uppercase tracking-widest">كيف يعمل؟</p>
            <h2 className="text-3xl md:text-4xl font-black">ابدأ في ٣ خطوات فقط</h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 relative">
            {/* Connector line (desktop) */}
            <div className="hidden md:block absolute top-8 right-[16.66%] left-[16.66%] h-px bg-gradient-to-l from-violet-500/30 via-teal-500/30 to-transparent" />

            {HOW_STEPS.map(step => (
              <div key={step.num} className="flex flex-col items-center text-center gap-4">
                <div className={`w-16 h-16 rounded-2xl ${step.ring} ring-2 flex items-center justify-center`}>
                  <span className={`text-2xl font-black ${step.color}`}>{step.num}</span>
                </div>
                <div>
                  <h3 className="font-bold text-base text-foreground mb-2">{step.title}</h3>
                  <p className="text-sm text-slate-400 leading-relaxed">{step.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ══════════════ CHAT DEMO ══════════════ */}
      <section className="py-24 px-6">
        <div className="max-w-5xl mx-auto grid md:grid-cols-2 gap-12 items-center">
          {/* Text */}
          <div className="space-y-6">
            <p className="text-teal-400 font-semibold text-sm uppercase tracking-widest">واجهة طبيعية</p>
            <h2 className="text-3xl font-black leading-tight">
              محادثات تبدو
              <br />
              <span className="text-teal-400">إنسانية تماماً</span>
            </h2>
            <p className="text-slate-400 leading-relaxed">
              البوت يرد بأسلوب عربي طبيعي ومريح، يفهم السياق، ويتذكر المحادثة كاملة.
              عملاؤك لن يشعروا أنهم يتحدثون مع آلة.
            </p>
            <ul className="space-y-3">
              {[
                'يفهم اللهجات العربية المختلفة',
                'يرد بالمنتجات والأسعار مباشرةً',
                'يقترح بدائل عند نفاد المخزون',
                'يحوّل الاستفسار لطلب شراء',
              ].map(point => (
                <li key={point} className="flex items-center gap-2.5 text-sm text-slate-300">
                  <span className="w-5 h-5 rounded-full bg-teal-500/15 border border-teal-500/30 flex items-center justify-center flex-shrink-0">
                    <Icon paths="M5 13l4 4L19 7" size={11} className="text-teal-400" />
                  </span>
                  {point}
                </li>
              ))}
            </ul>
          </div>

          {/* Chat mockup */}
          <div className="rounded-2xl border border-divider bg-content1 overflow-hidden shadow-2xl shadow-black/20">
            {/* Header */}
            <div className="flex items-center gap-3 px-4 py-3 border-b border-divider bg-content2">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-teal-500 to-cyan-600 flex items-center justify-center">
                <Icon paths="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" size={14} className="text-white" />
              </div>
              <div>
                <p className="text-xs font-bold text-foreground">مساعد المتجر</p>
                <p className="text-[10px] text-emerald-400 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  متاح الآن
                </p>
              </div>
            </div>

            {/* Messages */}
            <div className="p-4 space-y-3 min-h-[260px]">
              {/* Bot */}
              <div className="flex items-end gap-2">
                <div className="w-6 h-6 rounded-full bg-teal-500/20 flex items-center justify-center flex-shrink-0">
                  <Icon paths="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" size={11} className="text-teal-400" />
                </div>
                <div className="bg-content2 rounded-2xl rounded-br-sm px-4 py-2.5 max-w-[75%]">
                  <p className="text-sm text-foreground">أهلاً! كيف أقدر أساعدك؟ 😊</p>
                </div>
              </div>

              {/* User */}
              <div className="flex justify-start">
                <div className="bg-teal-500/15 border border-teal-500/20 rounded-2xl rounded-bl-sm px-4 py-2.5 max-w-[75%]">
                  <p className="text-sm text-foreground">عندكم طباعة على كروت شخصية؟</p>
                </div>
              </div>

              {/* Bot */}
              <div className="flex items-end gap-2">
                <div className="w-6 h-6 rounded-full bg-teal-500/20 flex items-center justify-center flex-shrink-0">
                  <Icon paths="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" size={11} className="text-teal-400" />
                </div>
                <div className="bg-content2 rounded-2xl rounded-br-sm px-4 py-2.5 max-w-[75%]">
                  <p className="text-sm text-foreground">
                    نعم! عندنا ٣ خيارات للكروت الشخصية:
                    <br />• كرت ورقي مطفي — ٥٠ ريال / ١٠٠ كرت
                    <br />• كرت مقوى لامع — ٨٠ ريال / ١٠٠ كرت
                    <br />• كرت UV فاخر — ١٢٠ ريال / ١٠٠ كرت
                    <br /><br />تبي تشوف أمثلة؟ 🖨️
                  </p>
                </div>
              </div>

              {/* User */}
              <div className="flex justify-start">
                <div className="bg-teal-500/15 border border-teal-500/20 rounded-2xl rounded-bl-sm px-4 py-2.5 max-w-[75%]">
                  <p className="text-sm text-foreground">أيش أسرع وقت توصيل؟</p>
                </div>
              </div>

              {/* Bot */}
              <div className="flex items-end gap-2">
                <div className="w-6 h-6 rounded-full bg-teal-500/20 flex items-center justify-center flex-shrink-0">
                  <Icon paths="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" size={11} className="text-teal-400" />
                </div>
                <div className="bg-content2 rounded-2xl rounded-br-sm px-4 py-2.5 max-w-[75%]">
                  <p className="text-sm text-foreground">التوصيل السريع خلال ٢٤ ساعة متاح للرياض وجدة 🚀</p>
                </div>
              </div>
            </div>

            {/* Input */}
            <div className="px-4 py-3 border-t border-divider bg-content2">
              <div className="flex items-center gap-2 bg-content1 rounded-xl px-3 py-2 border border-divider">
                <p className="text-sm text-slate-600 flex-1">اكتب سؤالك...</p>
                <div className="w-7 h-7 rounded-lg bg-teal-500/15 flex items-center justify-center">
                  <Icon paths="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" size={13} className="text-teal-400" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ══════════════ CTA BANNER ══════════════ */}
      <section className="py-24 px-6">
        <div className="max-w-3xl mx-auto">
          <div className="relative overflow-hidden rounded-3xl border border-teal-500/20 bg-gradient-to-br from-teal-500/10 via-cyan-500/5 to-transparent p-12 text-center space-y-6">
            <div className="absolute inset-0 bg-gradient-to-br from-teal-500/5 to-transparent pointer-events-none" />
            <div className="relative">
              <h2 className="text-3xl md:text-4xl font-black text-foreground mb-4">
                جاهز تبدأ؟
              </h2>
              <p className="text-slate-400 text-lg mb-8 max-w-xl mx-auto">
                انضم وشوف كيف يتحول متجرك لآلة مبيعات تعمل وحدها بينما أنت نايم.
              </p>
              <button
                onClick={handleCTA}
                className="inline-flex items-center gap-2.5 px-8 py-4 rounded-2xl font-bold text-base bg-gradient-to-l from-teal-500 to-cyan-500 text-white shadow-xl shadow-teal-500/30 hover:shadow-teal-500/50 hover:scale-[1.03] transition-all"
              >
                <Icon paths="M13 10V3L4 14h7v7l9-11h-7z" size={18} />
                ابدأ مجاناً الآن
              </button>
              <p className="text-xs text-slate-600 mt-4">لا يلزم بطاقة ائتمانية</p>
            </div>
          </div>
        </div>
      </section>

      {/* ══════════════ FOOTER ══════════════ */}
      <footer className="border-t border-divider py-8 px-6">
        <div className="max-w-6xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-teal-500 to-cyan-600 flex items-center justify-center">
              <Icon paths="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" size={14} className="text-white" />
            </div>
            <span className="font-black text-foreground">سلّابوت</span>
          </div>
          <p className="text-xs text-slate-600">
            © ٢٠٢٥ سلّابوت — بوت AI لمتاجر سلة
          </p>
          <button
            onClick={handleCTA}
            className="text-xs text-teal-400 hover:text-teal-300 font-semibold"
          >
            تسجيل الدخول ←
          </button>
        </div>
      </footer>

    </div>
  )
}
