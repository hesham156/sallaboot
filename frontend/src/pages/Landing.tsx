import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, useScroll, useTransform, AnimatePresence } from 'framer-motion'
import { AnimatedSection, StaggerContainer, StaggerItem, fadeUpVariants, staggerVariants } from '../components/AnimatedSection'
import { getToken, getIsSuper, getStoreId } from '../api'

// Inject the marketing chat widget once per page mount. The widget reads
// window.SallaChatConfig BEFORE its <script> evaluates, so we set the
// config first then append the script. Clean up on unmount so navigating
// to another route doesn't leave a stale widget behind.
function useSallabotWidget() {
  useEffect(() => {
    const SCRIPT_ID = 'sallabot-marketing-widget'
    if (document.getElementById(SCRIPT_ID)) return  // already loaded

    // window.SallaChatConfig is the public configuration contract — see
    // backend/widget.js for the keys it consumes.
    ;(window as unknown as { SallaChatConfig: Record<string, unknown> }).SallaChatConfig = {
      storeId:        'sallabot',
      apiUrl:         window.location.origin,
      storeName:      'حياك',
      primaryColor:   '#0d9488',  // teal-600 — matches the landing page
      position:       'left',     // RTL → left == far from the CTA buttons
      welcomeMessage: 'أهلاً! 👋 أنا حياك. اسألني عن أي حاجة عن المنتج: المميزات، الأسعار، التثبيت، أو احجز عرض حي.',
      placeholder:    'اكتب سؤالك...',
    }

    const s = document.createElement('script')
    s.id    = SCRIPT_ID
    s.src   = '/widget.js'
    s.async = true
    document.body.appendChild(s)

    return () => {
      // Best-effort teardown. The widget itself doesn't expose an
      // unmount API (it's a vanilla IIFE), so we just remove the
      // script tag — leaving the rendered button + iframe in place is
      // fine for SPA navigation since the user might come back.
      document.getElementById(SCRIPT_ID)?.remove()
    }
  }, [])
}

/* ─────────────────────────── Local motion helpers ─────────────────────────── */
const EASE = [0.25, 0.46, 0.45, 0.94] as const

const float = (delay = 0) => ({
  animate: { y: [0, -10, 0] },
  transition: { duration: 4, repeat: Infinity, ease: 'easeInOut', delay },
})

/* ─────────────────────────── Icon helper ─────────────────────────── */
function Icon({ d, size = 20, className = '' }: { d: string | string[]; size?: number; className?: string }) {
  const paths = Array.isArray(d) ? d : [d]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" className={className}>
      {paths.map((p, i) => <path key={i} d={p} />)}
    </svg>
  )
}
const ICONS = {
  bot:    ['M12 8V4H8', 'M4 8h16v12H4z', 'M2 14h2', 'M20 14h2', 'M9 13v2', 'M15 13v2'],
  calc:   ['M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z'],
  cart:   ['M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z'],
  chart:  ['M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z'],
  brain:  ['M9.5 2A2.5 2.5 0 0112 4.5v15a2.5 2.5 0 01-4.96.44 2.5 2.5 0 01-2.96-3.08 3 3 0 01-.34-5.58 2.5 2.5 0 011.32-4.24 2.5 2.5 0 014.44-1.04z', 'M14.5 2A2.5 2.5 0 0012 4.5v15a2.5 2.5 0 004.96.44 2.5 2.5 0 002.96-3.08 3 3 0 00.34-5.58 2.5 2.5 0 00-1.32-4.24 2.5 2.5 0 00-4.44-1.04z'],
  globe:  ['M12 21a9 9 0 100-18 9 9 0 000 18z', 'M3.6 9h16.8', 'M3.6 15h16.8', 'M12 3a14 14 0 010 18 14 14 0 010-18z'],
  check:  ['M5 13l4 4L19 7'],
  arrow:  ['M5 12h14', 'M13 6l6 6-6 6'],
  bolt:   ['M13 2L3 14h7v8l10-12h-7z'],
  star:   ['M12 2l3 7h7l-5.5 4 2 7L12 16l-6.5 4 2-7L2 9h7z'],
  spark:  ['M12 3v4', 'M12 17v4', 'M3 12h4', 'M17 12h4', 'M6 6l2.5 2.5', 'M15.5 15.5L18 18', 'M18 6l-2.5 2.5', 'M8.5 15.5L6 18'],
  shield: ['M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z', 'M9 12l2 2 4-4'],
  menu:   ['M4 6h16', 'M4 12h16', 'M4 18h16'],
  close:  ['M6 6l12 12', 'M18 6L6 18'],
}

/* ─────────────────────────── Section data ─────────────────────────── */
const FEATURES = [
  { icon: ICONS.bot,   title: 'مساعد مبيعات يبيع نيابةً عنك', desc: 'يفهم احتياج العميل، يرشّح المنتج المناسب، ويتمّ الطلب — ٢٤ ساعة بدون توقّف.', color: 'teal' },
  { icon: ICONS.calc,  title: 'حاسبة أسعار فورية',           desc: 'تسعير دقيق للطباعة (رول، ديجيتال، أوفست، علب) في ثوانٍ، بإعداداتك أنت.', color: 'cyan' },
  { icon: ICONS.cart,  title: 'استرجاع السلات المتروكة',      desc: 'يتابع العميل اللي ساب طلبه ويكمّله معاه — مبيعات كانت ضايعة.', color: 'amber' },
  { icon: ICONS.chart, title: 'تحليلات ذكية',                desc: 'مزاج العملاء، معدل التحويل، وأكثر الأسئلة — تعرف متجرك بالأرقام.', color: 'violet' },
  { icon: ICONS.brain, title: 'يتعلّم ويتطوّر',               desc: 'يستفيد من كل محادثة، ويطبّق تصحيحاتك، وما يكررش نفس الخطأ.', color: 'rose' },
  { icon: ICONS.globe, title: 'عربي بطلاقة',                 desc: 'يفهم لهجات الخليج ويرد بأسلوب ودّي طبيعي يناسب عملاءك.', color: 'sky' },
]
const STATS = [
  { num: '+200', label: 'متجر يثق بحياك' },
  { num: '٪89',  label: 'توفير في تكلفة الردود' },
  { num: '٪40',  label: 'زيادة في التحويل' },
  { num: '٢٤/٧', label: 'دعم بدون توقّف' },
]
const STEPS = [
  { n: '١', title: 'اربط متجرك', desc: 'تكامل مباشر مع سلة في دقيقة — بدون أكواد.' },
  { n: '٢', title: 'درّب البوت', desc: 'يقرأ منتجاتك وأسعارك تلقائياً، وتضيف لمساتك.' },
  { n: '٣', title: 'ابدأ تبيع', desc: 'البوت يرد، يسعّر، ويتمّ الطلبات — وانت مرتاح.' },
]

const COLOR_MAP: Record<string, string> = {
  teal:   'bg-teal-50 text-teal-600',
  cyan:   'bg-cyan-50 text-cyan-600',
  amber:  'bg-amber-50 text-amber-600',
  violet: 'bg-violet-50 text-violet-600',
  rose:   'bg-rose-50 text-rose-600',
  sky:    'bg-sky-50 text-sky-600',
}

/* ═══════════════════════════════ PAGE ═══════════════════════════════ */
export default function Landing() {
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const { scrollY } = useScroll()
  const heroY = useTransform(scrollY, [0, 500], [0, 60])

  // Mount the marketing chat widget (Sallabot answering questions about
  // itself). Backed by the "sallabot" demo store that bootstrap.py
  // registers on the backend at startup.
  useSallabotWidget()

  const loggedIn = !!getToken()
  function goDashboard() {
    if (!loggedIn) return navigate('/login')
    navigate(getIsSuper() ? '/admin' : `/store/${getStoreId()}`)
  }
  const cta = loggedIn ? 'لوحة التحكم' : 'ابدأ مجاناً'

  return (
    <div dir="rtl" className="min-h-screen bg-white text-slate-800 font-arabic overflow-x-hidden">

      {/* ── Promo bar ── */}
      <div className="bg-gradient-to-r from-teal-600 to-cyan-600 text-white text-center text-xs sm:text-sm font-semibold py-2 px-4">
        <span className="inline-flex items-center gap-2">
          <Icon d={ICONS.spark} size={14} />
          جرّب حياك مجاناً — مساعد مبيعات ذكي يشتغل على متجر سلة بتاعك
        </span>
      </div>

      {/* ── Navbar ── */}
      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-slate-100">
        <nav className="max-w-7xl mx-auto px-5 sm:px-8 h-16 flex items-center justify-between">
          <a href="/" className="flex items-center gap-2.5">
            <span className="w-9 h-9 rounded-xl bg-gradient-to-br from-teal-500 to-cyan-500 flex items-center justify-center text-white shadow-lg shadow-teal-500/25">
              <Icon d="M20 2H4a2 2 0 00-2 2v18l4-4h14a2 2 0 002-2V4a2 2 0 00-2-2z" size={18} />
            </span>
            <span className="font-black text-lg text-slate-900">حياك</span>
          </a>

          <div className="hidden md:flex items-center gap-8 text-sm font-semibold text-slate-600">
            <a href="#features" className="hover:text-teal-600 transition-colors">المميزات</a>
            <a href="#how"      className="hover:text-teal-600 transition-colors">كيف يعمل</a>
            <a href="#stats"    className="hover:text-teal-600 transition-colors">الأرقام</a>
          </div>

          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/login')} className="hidden sm:inline text-sm font-bold text-slate-700 hover:text-teal-600 transition-colors">
              تسجيل الدخول
            </button>
            <button onClick={goDashboard}
              className="inline-flex items-center gap-1.5 text-sm font-bold text-white bg-gradient-to-r from-teal-500 to-cyan-500 rounded-full px-4 sm:px-5 py-2.5 shadow-lg shadow-teal-500/25 hover:shadow-teal-500/40 hover:-translate-y-0.5 transition-all">
              {cta}
              <Icon d={ICONS.arrow} size={15} className="rotate-180" />
            </button>
            <button onClick={() => setMenuOpen(true)} className="md:hidden w-9 h-9 flex items-center justify-center text-slate-700" aria-label="القائمة">
              <Icon d={ICONS.menu} size={22} />
            </button>
          </div>
        </nav>
      </header>

      {/* ── Mobile menu ── */}
      <AnimatePresence>
        {menuOpen && (
          <>
            <motion.div className="fixed inset-0 bg-black/40 z-50 md:hidden"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              onClick={() => setMenuOpen(false)} />
            <motion.div className="fixed top-0 right-0 bottom-0 w-72 bg-white z-50 md:hidden p-6 shadow-2xl"
              initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
              transition={{ type: 'spring', damping: 28, stiffness: 280 }}>
              <div className="flex items-center justify-between mb-8">
                <span className="font-black text-lg text-slate-900">حياك</span>
                <button onClick={() => setMenuOpen(false)} className="text-slate-500"><Icon d={ICONS.close} size={22} /></button>
              </div>
              <div className="flex flex-col gap-1 text-base font-bold text-slate-700">
                {[['#features', 'المميزات'], ['#how', 'كيف يعمل'], ['#stats', 'الأرقام']].map(([h, t]) => (
                  <a key={h} href={h} onClick={() => setMenuOpen(false)} className="py-3 border-b border-slate-100">{t}</a>
                ))}
                <button onClick={() => { setMenuOpen(false); navigate('/login') }} className="py-3 text-right border-b border-slate-100">تسجيل الدخول</button>
                <button onClick={() => { setMenuOpen(false); goDashboard() }}
                  className="mt-4 text-white bg-gradient-to-r from-teal-500 to-cyan-500 rounded-full py-3 font-bold shadow-lg shadow-teal-500/25">
                  {cta}
                </button>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* ═══════════════ HERO ═══════════════ */}
      <section className="relative">
        {/* soft background glows */}
        <div className="absolute top-[-6rem] right-[-6rem] w-[34rem] h-[34rem] bg-teal-300/30 rounded-full blur-[130px] pointer-events-none" />
        <div className="absolute top-[10rem] left-[-8rem] w-[30rem] h-[30rem] bg-cyan-300/20 rounded-full blur-[130px] pointer-events-none" />
        <div className="absolute inset-0 bg-[radial-gradient(#e2e8f0_1px,transparent_1px)] [background-size:26px_26px] opacity-40 pointer-events-none" />

        <div className="relative max-w-7xl mx-auto px-5 sm:px-8 pt-16 sm:pt-24 pb-20 grid lg:grid-cols-2 gap-12 lg:gap-8 items-center">
          {/* copy */}
          <motion.div initial="hidden" animate="visible" variants={staggerVariants} className="text-center lg:text-right">
            <motion.div variants={fadeUpVariants} className="inline-flex items-center gap-2 bg-teal-50 border border-teal-100 text-teal-700 text-xs font-bold rounded-full px-3.5 py-1.5 mb-5">
              <span className="w-1.5 h-1.5 rounded-full bg-teal-500 animate-pulse" />
              مدعوم بالذكاء الاصطناعي — لمتاجر سلة
            </motion.div>
            <motion.h1 variants={fadeUpVariants} className="text-4xl sm:text-5xl lg:text-[3.4rem] font-black leading-[1.15] text-slate-900 tracking-tight">
              حوّل زوّار متجرك إلى
              <span className="text-gradient"> عملاء يشترون</span>
              <br className="hidden sm:block" /> بمساعد ذكي يبيع نيابةً عنك
            </motion.h1>
            <motion.p variants={fadeUpVariants} className="mt-5 text-base sm:text-lg text-slate-600 leading-relaxed max-w-xl mx-auto lg:mx-0">
              حياك يجاوب عملاءك فوراً، يحسب الأسعار، يسترجع السلات المتروكة، ويتعلّم من كل محادثة — كل ده على متجرك في سلة، بالعربي.
            </motion.p>
            <motion.div variants={fadeUpVariants} className="mt-8 flex flex-wrap items-center justify-center lg:justify-start gap-3">
              <button onClick={goDashboard}
                className="inline-flex items-center gap-2 text-base font-bold text-white bg-gradient-to-r from-teal-500 to-cyan-500 rounded-full px-7 py-3.5 shadow-xl shadow-teal-500/25 hover:shadow-teal-500/40 hover:-translate-y-0.5 transition-all">
                {cta}
                <Icon d={ICONS.arrow} size={18} className="rotate-180" />
              </button>
              <a href="#how" className="inline-flex items-center gap-2 text-base font-bold text-slate-700 bg-white border border-slate-200 rounded-full px-6 py-3.5 hover:border-teal-300 hover:text-teal-600 transition-all">
                <Icon d={ICONS.bolt} size={18} />
                شاهد كيف يعمل
              </a>
            </motion.div>
            {/* social proof */}
            <motion.div variants={fadeUpVariants} className="mt-8 flex items-center justify-center lg:justify-start gap-3">
              <div className="flex -space-x-2 space-x-reverse">
                {['#14b8a6', '#06b6d4', '#0ea5e9', '#8b5cf6'].map((c, i) => (
                  <span key={i} className="w-9 h-9 rounded-full border-2 border-white flex items-center justify-center text-white text-xs font-bold" style={{ background: c }}>
                    {['م', 'س', 'ك', 'ع'][i]}
                  </span>
                ))}
              </div>
              <div className="text-right">
                <div className="flex items-center gap-0.5 text-amber-400">
                  {[...Array(5)].map((_, i) => <Icon key={i} d={ICONS.star} size={13} className="fill-amber-400" />)}
                </div>
                <p className="text-xs font-semibold text-slate-500 mt-0.5">+200 متجر يبيع أكتر مع حياك</p>
              </div>
            </motion.div>
          </motion.div>

          {/* hero mockup */}
          <motion.div style={{ y: heroY }} initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.7, ease: EASE }} className="relative mx-auto w-full max-w-md">
            <div className="relative rounded-[2rem] bg-gradient-to-br from-teal-400 to-cyan-500 p-5 shadow-2xl shadow-teal-500/30">
              {/* chat card */}
              <div className="rounded-3xl bg-white p-4 shadow-xl">
                <div className="flex items-center gap-2.5 pb-3 border-b border-slate-100">
                  <span className="w-8 h-8 rounded-full bg-gradient-to-br from-teal-500 to-cyan-500 flex items-center justify-center text-white text-sm">🤖</span>
                  <div>
                    <p className="text-sm font-bold text-slate-800">مساعد المتجر</p>
                    <p className="text-[10px] text-emerald-500 font-semibold flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />متصل الآن</p>
                  </div>
                </div>
                <div className="space-y-2.5 py-3 text-[13px]">
                  <div className="bg-slate-100 text-slate-700 rounded-2xl rounded-tr-sm px-3 py-2 w-fit max-w-[80%] mr-auto">عايز أطبع 1000 كرت</div>
                  <div className="bg-gradient-to-br from-teal-500 to-cyan-500 text-white rounded-2xl rounded-tl-sm px-3 py-2 w-fit max-w-[85%] ml-auto leading-relaxed">
                    تمام! 9×5 سم كوشيه 300، وجهين<br />💵 السعر شامل الضريبة: <b>103.50 ريال</b>
                  </div>
                  <div className="bg-slate-100 text-slate-700 rounded-2xl rounded-tr-sm px-3 py-2 w-fit mr-auto">أكمل الطلب 👍</div>
                </div>
              </div>
            </div>

            {/* floating cards */}
            <motion.div {...float(0)} className="absolute -top-4 -left-5 bg-white rounded-2xl shadow-xl border border-slate-100 px-3.5 py-2.5 flex items-center gap-2.5">
              <span className="w-8 h-8 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center"><Icon d={ICONS.check} size={16} /></span>
              <div><p className="text-[10px] text-slate-400 font-semibold">طلب جديد</p><p className="text-sm font-black text-slate-800">+103.50 ر.س</p></div>
            </motion.div>
            <motion.div {...float(1.2)} className="absolute -bottom-5 -right-4 bg-white rounded-2xl shadow-xl border border-slate-100 px-3.5 py-2.5 flex items-center gap-2.5">
              <span className="w-8 h-8 rounded-lg bg-teal-50 text-teal-600 flex items-center justify-center"><Icon d={ICONS.chart} size={16} /></span>
              <div><p className="text-[10px] text-slate-400 font-semibold">التحويل</p><p className="text-sm font-black text-slate-800">٪40 ▲</p></div>
            </motion.div>
          </motion.div>
        </div>
      </section>

      {/* ═══════════════ STATS ═══════════════ */}
      <section id="stats" className="border-y border-slate-100 bg-slate-50/60">
        <StaggerContainer className="max-w-7xl mx-auto px-5 sm:px-8 py-12 grid grid-cols-2 lg:grid-cols-4 gap-8">
          {STATS.map((s) => (
            <StaggerItem key={s.label} className="text-center">
              <p className="text-3xl sm:text-4xl font-black text-gradient">{s.num}</p>
              <p className="text-sm font-semibold text-slate-500 mt-1">{s.label}</p>
            </StaggerItem>
          ))}
        </StaggerContainer>
      </section>

      {/* ═══════════════ FEATURES (bento) ═══════════════ */}
      <section id="features" className="max-w-7xl mx-auto px-5 sm:px-8 py-20 sm:py-28">
        <StaggerContainer className="text-center max-w-2xl mx-auto mb-14">
          <motion.span variants={fadeUpVariants} className="inline-block text-xs font-bold text-teal-600 bg-teal-50 rounded-full px-3 py-1 mb-4">كل اللي متجرك محتاجه</motion.span>
          <motion.h2 variants={fadeUpVariants} className="text-3xl sm:text-4xl font-black text-slate-900 leading-tight">مساعد واحد يقوم بعمل فريق مبيعات كامل</motion.h2>
          <motion.p variants={fadeUpVariants} className="text-base text-slate-600 mt-4">من أول رسالة للعميل لحد إتمام الطلب — حياك معاك في كل خطوة.</motion.p>
        </StaggerContainer>

        <StaggerContainer className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {FEATURES.map((f) => (
            <motion.div key={f.title} variants={fadeUpVariants} whileHover={{ y: -6 }}
              className="group bg-white border border-slate-100 rounded-3xl p-7 shadow-[0_4px_24px_rgba(15,23,42,0.05)] hover:shadow-[0_12px_36px_rgba(20,184,166,0.12)] transition-shadow">
              <div className={`w-12 h-12 rounded-2xl flex items-center justify-center mb-5 ${COLOR_MAP[f.color]}`}>
                <Icon d={f.icon} size={24} />
              </div>
              <h3 className="text-lg font-black text-slate-900 mb-2">{f.title}</h3>
              <p className="text-sm text-slate-600 leading-relaxed">{f.desc}</p>
            </motion.div>
          ))}
        </StaggerContainer>

        {/* wide dark highlight card */}
        <AnimatedSection className="mt-5 relative overflow-hidden rounded-3xl bg-slate-900 text-white p-8 sm:p-12 grid lg:grid-cols-2 gap-8 items-center">
          <div className="absolute top-[-4rem] left-[-4rem] w-72 h-72 bg-teal-500/20 rounded-full blur-3xl" />
          <div className="relative">
            <span className="inline-flex items-center gap-2 text-xs font-bold text-teal-300 bg-teal-500/10 rounded-full px-3 py-1 mb-4">
              <Icon d={ICONS.shield} size={14} /> سرّي وآمن
            </span>
            <h3 className="text-2xl sm:text-3xl font-black leading-tight mb-3">يتعلّم من كل محادثة — ويوفّر تكلفتك</h3>
            <p className="text-slate-300 leading-relaxed">حياك يلتقط تصحيحاتك ويطبّقها، ويرد على الأسئلة المتكررة بدون ذكاء اصطناعي — توفير يوصل ٪89 من التكلفة مع كل ما يتعلّم أكثر.</p>
            <button onClick={goDashboard} className="mt-6 inline-flex items-center gap-2 text-sm font-bold text-slate-900 bg-white rounded-full px-5 py-3 hover:bg-teal-50 transition-colors">
              ابدأ الآن <Icon d={ICONS.arrow} size={16} className="rotate-180" />
            </button>
          </div>
          <div className="relative grid grid-cols-2 gap-3">
            {[['🧠', 'يتذكر كل عميل'], ['⚡', 'رد لحظي'], ['💰', 'توفير ٪89'], ['🔒', 'بياناتك محمية']].map(([e, t]) => (
              <div key={t} className="bg-white/5 border border-white/10 rounded-2xl p-4 text-center backdrop-blur-sm">
                <div className="text-2xl mb-1.5">{e}</div>
                <p className="text-xs font-semibold text-slate-200">{t}</p>
              </div>
            ))}
          </div>
        </AnimatedSection>
      </section>

      {/* ═══════════════ HOW IT WORKS ═══════════════ */}
      <section id="how" className="bg-slate-50/60 border-y border-slate-100">
        <div className="max-w-7xl mx-auto px-5 sm:px-8 py-20 sm:py-28">
          <StaggerContainer className="text-center max-w-2xl mx-auto mb-14">
            <motion.h2 variants={fadeUpVariants} className="text-3xl sm:text-4xl font-black text-slate-900">ابدأ في ٣ خطوات بسيطة</motion.h2>
            <motion.p variants={fadeUpVariants} className="text-base text-slate-600 mt-4">من الربط لأول عملية بيع — بدون تعقيد ولا أكواد.</motion.p>
          </StaggerContainer>
          <StaggerContainer className="grid md:grid-cols-3 gap-6">
            {STEPS.map((s) => (
              <StaggerItem key={s.n} className="relative bg-white border border-slate-100 rounded-3xl p-8 shadow-[0_4px_24px_rgba(15,23,42,0.05)]">
                <span className="absolute -top-5 right-7 w-12 h-12 rounded-2xl bg-gradient-to-br from-teal-500 to-cyan-500 text-white text-xl font-black flex items-center justify-center shadow-lg shadow-teal-500/30">{s.n}</span>
                <h3 className="text-lg font-black text-slate-900 mt-4 mb-2">{s.title}</h3>
                <p className="text-sm text-slate-600 leading-relaxed">{s.desc}</p>
              </StaggerItem>
            ))}
          </StaggerContainer>
        </div>
      </section>

      {/* ═══════════════ CTA ═══════════════ */}
      <section className="max-w-7xl mx-auto px-5 sm:px-8 py-20 sm:py-24">
        <AnimatedSection className="relative overflow-hidden rounded-[2.5rem] bg-gradient-to-br from-teal-500 to-cyan-500 px-7 sm:px-14 py-14 sm:py-20 text-center text-white">
          <div className="absolute top-[-5rem] right-[-3rem] w-80 h-80 bg-white/15 rounded-full blur-3xl" />
          <div className="absolute bottom-[-6rem] left-[-3rem] w-80 h-80 bg-white/10 rounded-full blur-3xl" />
          <div className="relative">
            <h2 className="text-3xl sm:text-5xl font-black leading-tight">جاهز تبيع أكتر؟</h2>
            <p className="mt-4 text-base sm:text-lg text-teal-50 max-w-xl mx-auto">فعّل حياك على متجرك النهاردة، وخلّي مساعد ذكي يشتغل لك ٢٤ ساعة.</p>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              <button onClick={goDashboard} className="inline-flex items-center gap-2 text-base font-black text-teal-600 bg-white rounded-full px-8 py-4 shadow-xl hover:-translate-y-0.5 transition-transform">
                {cta} <Icon d={ICONS.arrow} size={18} className="rotate-180" />
              </button>
              <button onClick={() => navigate('/login')} className="inline-flex items-center text-base font-bold text-white border border-white/40 rounded-full px-7 py-4 hover:bg-white/10 transition-colors">
                تسجيل الدخول
              </button>
            </div>
          </div>
        </AnimatedSection>
      </section>

      {/* ═══════════════ FOOTER ═══════════════ */}
      <footer className="border-t border-slate-100">
        <div className="max-w-7xl mx-auto px-5 sm:px-8 py-12 flex flex-col sm:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-2.5">
            <span className="w-8 h-8 rounded-lg bg-gradient-to-br from-teal-500 to-cyan-500 flex items-center justify-center text-white">
              <Icon d="M20 2H4a2 2 0 00-2 2v18l4-4h14a2 2 0 002-2V4a2 2 0 00-2-2z" size={16} />
            </span>
            <span className="font-black text-slate-900">حياك</span>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm font-semibold text-slate-500">
            <a href="#features" className="hover:text-teal-600 transition-colors">المميزات</a>
            <a href="#how" className="hover:text-teal-600 transition-colors">كيف يعمل</a>
            <button onClick={() => navigate('/privacy')} className="hover:text-teal-600 transition-colors">سياسة الخصوصية</button>
            <button onClick={() => navigate('/terms')} className="hover:text-teal-600 transition-colors">شروط الخدمة</button>
            <button onClick={() => navigate('/data-deletion')} className="hover:text-teal-600 transition-colors">حذف البيانات</button>
            <button onClick={() => navigate('/login')} className="hover:text-teal-600 transition-colors">تسجيل الدخول</button>
          </div>
          <p className="text-xs text-slate-400">© {new Date().getFullYear()} حياك — المساعد الذكي لمتاجر سلة</p>
        </div>
      </footer>
    </div>
  )
}
