import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getToken, getIsSuper, getStoreId } from '../api'

/* ── Tiny icon helper ── */
function Icon({ d, size = 20, className = '' }: { d: string | string[]; size?: number; className?: string }) {
  const paths = Array.isArray(d) ? d : [d]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round"
      className={className}>
      {paths.map((p, i) => <path key={i} d={p} />)}
    </svg>
  )
}

/* ── Data ── */
const STATS = [
  { value: '+٥٠٠', label: 'متجر نشط' },
  { value: '٩٧٪', label: 'رضا العملاء' },
  { value: '٢٤/٧', label: 'متاح دائماً' },
  { value: '<٢ث', label: 'زمن الرد' },
]

const FEATURES = [
  {
    icon: 'M8 10h.01M12 10h.01M16 10h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z',
    title: 'دردشة ذكية بالعربية',
    desc: 'بوت يفهم اللهجات العربية المختلفة ويرد بشكل طبيعي على أسئلة عملاءك.',
    color: 'from-violet-500/20 to-violet-500/0',
    border: 'border-violet-500/20',
    dot: 'bg-violet-500',
  },
  {
    icon: 'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4',
    title: 'مزامنة تلقائية مع سلة',
    desc: 'البوت يتعلم منتجاتك وأسعارك مباشرةً ويحدّث نفسه عند أي تغيير.',
    color: 'from-cyan-500/20 to-cyan-500/0',
    border: 'border-cyan-500/20',
    dot: 'bg-cyan-500',
  },
  {
    icon: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z',
    title: 'تحليلات وتقارير',
    desc: 'تابع أداء البوت وأكثر الأسئلة تكراراً ومعدلات التحويل في لحظة.',
    color: 'from-emerald-500/20 to-emerald-500/0',
    border: 'border-emerald-500/20',
    dot: 'bg-emerald-500',
  },
  {
    icon: 'M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z',
    title: 'تدريب مخصص',
    desc: 'علّم البوت شخصية متجرك وسياساتك وأسلوبك الخاص في التواصل.',
    color: 'from-amber-500/20 to-amber-500/0',
    border: 'border-amber-500/20',
    dot: 'bg-amber-500',
  },
  {
    icon: 'M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z',
    title: 'استرداد السلات المتروكة',
    desc: 'البوت يتابع العملاء اللي تركوا الطلب ويحوّلهم لمبيعات حقيقية.',
    color: 'from-rose-500/20 to-rose-500/0',
    border: 'border-rose-500/20',
    dot: 'bg-rose-500',
  },
  {
    icon: 'M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z',
    title: 'أمان وعزل تام',
    desc: 'كل متجر في بيئة مستقلة مع تشفير كامل للبيانات والمحادثات.',
    color: 'from-blue-500/20 to-blue-500/0',
    border: 'border-blue-500/20',
    dot: 'bg-blue-500',
  },
]

const PRICING = [
  {
    name: 'مجاني',
    price: '٠',
    period: 'دائماً',
    desc: 'للمتاجر الصغيرة اللي تبدأ رحلتها',
    features: ['بوت AI أساسي', 'حتى ٢٠٠ رسالة/شهر', 'مزامنة المنتجات', 'دعم عبر البريد'],
    cta: 'ابدأ مجاناً',
    highlight: false,
  },
  {
    name: 'برو',
    price: '٩٩',
    period: 'شهرياً',
    desc: 'للمتاجر الجادة اللي تريد نمواً حقيقياً',
    features: ['رسائل غير محدودة', 'تحليلات متقدمة', 'تدريب مخصص', 'سلات متروكة', 'دعم أولوية ٢٤/٧'],
    cta: 'جرّب ٧ أيام مجاناً',
    highlight: true,
    badge: 'الأكثر شيوعاً',
  },
  {
    name: 'مؤسسي',
    price: '٢٩٩',
    period: 'شهرياً',
    desc: 'للمتاجر الكبيرة والشركات',
    features: ['كل مزايا برو', 'متاجر متعددة', 'API مخصص', 'مدير حساب مخصص', 'SLA مضمون'],
    cta: 'تواصل معنا',
    highlight: false,
  },
]

const TESTIMONIALS = [
  {
    name: 'أحمد السيد',
    role: 'صاحب متجر طباعة — جدة',
    text: 'البوت وفّر عليّ ساعات يومياً في الرد على نفس الأسئلة. المبيعات زادت ٣٠٪ في أول شهر.',
    avatar: 'أ',
    color: 'from-violet-500 to-purple-600',
  },
  {
    name: 'سارة المطيري',
    role: 'مديرة متجر إلكتروني — الرياض',
    text: 'كنت أفكر في توظيف موظف للرد، البوت حل المشكلة بعُشر التكلفة وبشكل أفضل.',
    avatar: 'س',
    color: 'from-cyan-500 to-teal-600',
  },
  {
    name: 'محمد العتيبي',
    role: 'صاحب متجر مستلزمات — الدمام',
    text: 'المزامنة مع سلة مذهلة — البوت يعرف كل منتج بأدق التفاصيل ويقترح البديل تلقائياً.',
    avatar: 'م',
    color: 'from-emerald-500 to-teal-600',
  },
]

const FAQS = [
  { q: 'هل يعمل البوت مع أي متجر سلة؟', a: 'نعم، يعمل مع جميع متاجر سلة. تحتاج فقط لربط متجرك عبر Access Token.' },
  { q: 'كيف يتعلم البوت منتجاتي؟', a: 'يتصل مباشرةً بـ API سلة ويسحب كل المنتجات والأسعار والتصنيفات تلقائياً.' },
  { q: 'هل بيانات عملائي آمنة؟', a: 'كل متجر معزول تماماً في بيئة مستقلة مع تشفير SSL وتشفير قاعدة البيانات.' },
  { q: 'ماذا يحدث لو لم يعرف البوت الإجابة؟', a: 'يخبر العميل بأدب أنه سيحوّله لفريق الدعم ويسجّل السؤال لتحسينه.' },
  { q: 'هل يمكنني تخصيص أسلوب البوت؟', a: 'بالكامل — تحكم في الشخصية، الأسلوب، الأسئلة الشائعة، والردود الافتراضية.' },
]

/* ── Styles shared ── */
const glassCard = 'bg-white/[0.03] border border-white/[0.08] rounded-2xl backdrop-blur-sm'

export default function Landing() {
  const navigate  = useNavigate()
  const [openFaq, setOpenFaq] = useState<number | null>(null)

  function handleCTA() {
    const token = getToken()
    if (!token) { navigate('/login'); return }
    navigate(getIsSuper() ? '/admin' : `/store/${getStoreId()}`)
  }

  return (
    <div
      className="min-h-screen text-white overflow-x-hidden"
      style={{ background: 'linear-gradient(135deg, #07071a 0%, #0d0820 50%, #07071a 100%)' }}
      dir="rtl"
    >
      {/* ── Global glow orbs ── */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div style={{ position: 'absolute', top: '-10%', left: '30%', width: 600, height: 600, background: 'radial-gradient(circle, rgba(139,92,246,0.12) 0%, transparent 70%)', borderRadius: '50%' }} />
        <div style={{ position: 'absolute', top: '40%', right: '-5%', width: 400, height: 400, background: 'radial-gradient(circle, rgba(6,182,212,0.08) 0%, transparent 70%)', borderRadius: '50%' }} />
        <div style={{ position: 'absolute', bottom: '10%', left: '10%', width: 500, height: 500, background: 'radial-gradient(circle, rgba(139,92,246,0.08) 0%, transparent 70%)', borderRadius: '50%' }} />
      </div>

      {/* ══════════ NAV ══════════ */}
      <nav style={{ position: 'sticky', top: 0, zIndex: 50, borderBottom: '1px solid rgba(255,255,255,0.06)', background: 'rgba(7,7,26,0.8)', backdropFilter: 'blur(20px)' }}>
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div style={{ width: 36, height: 36, borderRadius: 10, background: 'linear-gradient(135deg, #8b5cf6, #06b6d4)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Icon d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" size={16} className="text-white" />
            </div>
            <span style={{ fontWeight: 900, fontSize: 18 }}>سلّابوت</span>
          </div>

          <div className="hidden md:flex items-center gap-8">
            {['المزايا', 'الأسعار', 'الآراء', 'الأسئلة'].map(item => (
              <a key={item} href={`#${item}`} style={{ color: 'rgba(255,255,255,0.6)', fontSize: 14, fontWeight: 500 }}
                className="hover:text-white transition-colors">{item}</a>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <button onClick={handleCTA} style={{ color: 'rgba(255,255,255,0.6)', fontSize: 14, fontWeight: 600, padding: '8px 16px' }}
              className="hover:text-white transition-colors">
              تسجيل الدخول
            </button>
            <button onClick={handleCTA}
              style={{ background: 'linear-gradient(135deg, #8b5cf6, #06b6d4)', borderRadius: 10, padding: '9px 20px', fontSize: 14, fontWeight: 700, color: '#fff' }}
              className="hover:opacity-90 transition-opacity">
              ابدأ مجاناً
            </button>
          </div>
        </div>
      </nav>

      {/* ══════════ HERO ══════════ */}
      <section className="relative pt-28 pb-20 px-6 text-center">
        {/* Badge */}
        <div className="inline-flex items-center gap-2 mb-8" style={{ padding: '6px 16px', borderRadius: 999, border: '1px solid rgba(139,92,246,0.3)', background: 'rgba(139,92,246,0.1)' }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#a78bfa', display: 'inline-block', animation: 'pulse 2s infinite' }} />
          <span style={{ fontSize: 13, color: '#c4b5fd', fontWeight: 600 }}>مدعوم بأحدث نماذج الذكاء الاصطناعي</span>
        </div>

        {/* Headline */}
        <h1 className="mx-auto" style={{ maxWidth: 760, fontSize: 'clamp(40px, 6vw, 72px)', fontWeight: 900, lineHeight: 1.1, marginBottom: 24 }}>
          بوت يبيع لك{' '}
          <span style={{ background: 'linear-gradient(90deg, #a78bfa, #38bdf8, #34d399)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
            وأنت نايم
          </span>
        </h1>

        <p style={{ fontSize: 18, color: 'rgba(255,255,255,0.55)', lineHeight: 1.7, maxWidth: 560, margin: '0 auto 40px' }}>
          مساعد AI يتحدث مع عملاء متجرك على سلة، يشرح المنتجات، يتابع الطلبات،
          ويحوّل الاستفسارات لمبيعات — على مدار الساعة.
        </p>

        {/* CTAs */}
        <div className="flex items-center justify-center gap-3 flex-wrap mb-16">
          <button onClick={handleCTA}
            style={{ background: 'linear-gradient(135deg, #8b5cf6, #06b6d4)', borderRadius: 14, padding: '14px 32px', fontSize: 16, fontWeight: 800, color: '#fff', boxShadow: '0 0 40px rgba(139,92,246,0.35)' }}
            className="hover:opacity-90 hover:scale-[1.02] transition-all flex items-center gap-2">
            <Icon d="M13 10V3L4 14h7v7l9-11h-7z" size={18} />
            ابدأ مجاناً الآن
          </button>
          <button onClick={handleCTA}
            style={{ borderRadius: 14, padding: '14px 32px', fontSize: 16, fontWeight: 700, color: 'rgba(255,255,255,0.8)', border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.04)' }}
            className="hover:bg-white/10 transition-all flex items-center gap-2">
            <Icon d="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" size={18} />
            شاهد العرض
          </button>
        </div>

        {/* Chat mockup */}
        <div className="mx-auto" style={{ maxWidth: 480, borderRadius: 20, border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.03)', backdropFilter: 'blur(20px)', overflow: 'hidden', boxShadow: '0 40px 80px rgba(0,0,0,0.5), 0 0 60px rgba(139,92,246,0.1)' }}>
          {/* Bar */}
          <div style={{ padding: '12px 16px', borderBottom: '1px solid rgba(255,255,255,0.06)', display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 32, height: 32, borderRadius: '50%', background: 'linear-gradient(135deg,#8b5cf6,#06b6d4)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Icon d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" size={14} className="text-white" />
            </div>
            <div>
              <p style={{ fontSize: 12, fontWeight: 700, color: '#fff' }}>مساعد المتجر</p>
              <p style={{ fontSize: 10, color: '#34d399', display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#34d399', display: 'inline-block' }} />
                متصل الآن
              </p>
            </div>
          </div>
          {/* Messages */}
          <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
            {[
              { from: 'bot', text: 'أهلاً! كيف أقدر أساعدك؟ 😊' },
              { from: 'user', text: 'عندكم طباعة على كروت شخصية؟' },
              { from: 'bot', text: 'نعم! عندنا ٣ خيارات:\n• مطفي — ٥٠ ريال/١٠٠ كرت\n• لامع — ٨٠ ريال/١٠٠ كرت\n• UV فاخر — ١٢٠ ريال/١٠٠ كرت 🖨️' },
              { from: 'user', text: 'ما هو أسرع وقت توصيل؟' },
              { from: 'bot', text: 'خلال ٢٤ ساعة للرياض وجدة بالشحن السريع 🚀' },
            ].map((m, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: m.from === 'user' ? 'flex-start' : 'flex-end' }}>
                <div style={{
                  maxWidth: '75%',
                  padding: '10px 14px',
                  borderRadius: m.from === 'bot' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                  background: m.from === 'bot'
                    ? 'linear-gradient(135deg,rgba(139,92,246,0.25),rgba(6,182,212,0.15))'
                    : 'rgba(255,255,255,0.08)',
                  border: '1px solid rgba(255,255,255,0.08)',
                  fontSize: 13,
                  color: '#e2e8f0',
                  lineHeight: 1.6,
                  whiteSpace: 'pre-line',
                  textAlign: 'right',
                }}>
                  {m.text}
                </div>
              </div>
            ))}
          </div>
          {/* Input */}
          <div style={{ padding: '10px 16px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ borderRadius: 12, border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.04)', padding: '8px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.3)' }}>اكتب رسالتك...</span>
              <div style={{ width: 28, height: 28, borderRadius: 8, background: 'linear-gradient(135deg,#8b5cf6,#06b6d4)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Icon d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" size={13} className="text-white" />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ══════════ STATS ══════════ */}
      <section style={{ borderTop: '1px solid rgba(255,255,255,0.06)', borderBottom: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)', padding: '48px 24px' }}>
        <div className="max-w-4xl mx-auto grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
          {STATS.map(s => (
            <div key={s.value}>
              <p style={{ fontSize: 40, fontWeight: 900, background: 'linear-gradient(90deg,#a78bfa,#38bdf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', lineHeight: 1 }}>
                {s.value}
              </p>
              <p style={{ fontSize: 13, color: 'rgba(255,255,255,0.5)', marginTop: 8, fontWeight: 500 }}>{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ══════════ FEATURES ══════════ */}
      <section id="المزايا" className="py-24 px-6">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-16">
            <p style={{ fontSize: 13, color: '#a78bfa', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 12 }}>المزايا</p>
            <h2 style={{ fontSize: 'clamp(28px,4vw,44px)', fontWeight: 900, marginBottom: 16 }}>كل ما يحتاجه متجرك</h2>
            <p style={{ color: 'rgba(255,255,255,0.5)', fontSize: 16, maxWidth: 480, margin: '0 auto' }}>
              منظومة متكاملة مصممة خصيصاً لمتاجر سلة
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {FEATURES.map(f => (
              <div key={f.title} style={{ borderRadius: 20, border: `1px solid`, borderColor: f.border.replace('border-', ''), padding: 24, background: 'rgba(255,255,255,0.02)', position: 'relative', overflow: 'hidden' }}
                className={`${f.border} hover:bg-white/[0.04] transition-all duration-300 hover:-translate-y-1`}>
                <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(135deg, ${f.color.replace('from-', '').replace('/20', '').replace(' to-', ', ').replace('/0', '')} transparent)`, opacity: 0.5, pointerEvents: 'none' }} />
                <div style={{ position: 'relative' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
                    <div style={{ width: 10, height: 10, borderRadius: '50%' }} className={f.dot} />
                    <span style={{ fontSize: 16, fontWeight: 700 }}>{f.title}</span>
                  </div>
                  <p style={{ fontSize: 14, color: 'rgba(255,255,255,0.5)', lineHeight: 1.7 }}>{f.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ══════════ HOW IT WORKS ══════════ */}
      <section style={{ background: 'rgba(255,255,255,0.02)', borderTop: '1px solid rgba(255,255,255,0.06)', borderBottom: '1px solid rgba(255,255,255,0.06)', padding: '96px 24px' }}>
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p style={{ fontSize: 13, color: '#38bdf8', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 12 }}>كيف يعمل؟</p>
            <h2 style={{ fontSize: 'clamp(28px,4vw,44px)', fontWeight: 900 }}>ابدأ في ٣ خطوات فقط</h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 relative">
            {/* Connector */}
            <div className="hidden md:block absolute top-10 right-[18%] left-[18%] h-px" style={{ background: 'linear-gradient(90deg, transparent, rgba(139,92,246,0.4), rgba(6,182,212,0.4), transparent)' }} />

            {[
              { num: '١', title: 'سجّل متجرك', desc: 'اربط متجر سلة بـ Access Token في أقل من دقيقة.', color: '#8b5cf6' },
              { num: '٢', title: 'اضبط البوت', desc: 'خصّص الشخصية والأسلوب ودرّبه على أسئلة عملاءك.', color: '#06b6d4' },
              { num: '٣', title: 'ابدأ البيع', desc: 'فعّله وشاهد المحادثات تتحول لمبيعات تلقائياً.', color: '#34d399' },
            ].map(step => (
              <div key={step.num} className="flex flex-col items-center text-center gap-4">
                <div style={{ width: 64, height: 64, borderRadius: 18, border: `2px solid ${step.color}40`, background: `${step.color}15`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <span style={{ fontSize: 26, fontWeight: 900, color: step.color }}>{step.num}</span>
                </div>
                <div>
                  <h3 style={{ fontSize: 17, fontWeight: 700, marginBottom: 8 }}>{step.title}</h3>
                  <p style={{ fontSize: 14, color: 'rgba(255,255,255,0.5)', lineHeight: 1.7 }}>{step.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ══════════ PRICING ══════════ */}
      <section id="الأسعار" className="py-24 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p style={{ fontSize: 13, color: '#a78bfa', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 12 }}>الأسعار</p>
            <h2 style={{ fontSize: 'clamp(28px,4vw,44px)', fontWeight: 900, marginBottom: 12 }}>بسيط وشفاف، بدون مفاجآت</h2>
            <p style={{ color: 'rgba(255,255,255,0.5)', fontSize: 16 }}>لا رسوم خفية، لا عقود طويلة</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {PRICING.map(plan => (
              <div key={plan.name} style={{
                borderRadius: 24,
                border: plan.highlight ? '1px solid rgba(139,92,246,0.5)' : '1px solid rgba(255,255,255,0.08)',
                background: plan.highlight ? 'linear-gradient(135deg, rgba(139,92,246,0.12), rgba(6,182,212,0.06))' : 'rgba(255,255,255,0.02)',
                padding: 32,
                position: 'relative',
                boxShadow: plan.highlight ? '0 0 60px rgba(139,92,246,0.15)' : 'none',
              }}>
                {plan.badge && (
                  <div style={{ position: 'absolute', top: -12, right: 24, background: 'linear-gradient(90deg,#8b5cf6,#06b6d4)', borderRadius: 999, padding: '4px 14px', fontSize: 11, fontWeight: 700 }}>
                    {plan.badge}
                  </div>
                )}
                <p style={{ fontSize: 14, color: 'rgba(255,255,255,0.5)', marginBottom: 8 }}>{plan.name}</p>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginBottom: 8 }}>
                  <span style={{ fontSize: 44, fontWeight: 900, color: plan.highlight ? '#a78bfa' : '#fff' }}>{plan.price}</span>
                  <span style={{ fontSize: 14, color: 'rgba(255,255,255,0.4)' }}>ريال/{plan.period}</span>
                </div>
                <p style={{ fontSize: 13, color: 'rgba(255,255,255,0.4)', marginBottom: 24, lineHeight: 1.6 }}>{plan.desc}</p>
                <ul style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 28 }}>
                  {plan.features.map(f => (
                    <li key={f} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14, color: 'rgba(255,255,255,0.75)' }}>
                      <div style={{ width: 18, height: 18, borderRadius: '50%', background: 'rgba(52,211,153,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                        <Icon d="M5 13l4 4L19 7" size={11} className="text-emerald-400" />
                      </div>
                      {f}
                    </li>
                  ))}
                </ul>
                <button onClick={handleCTA} style={{
                  width: '100%',
                  padding: '12px',
                  borderRadius: 12,
                  fontSize: 15,
                  fontWeight: 700,
                  background: plan.highlight ? 'linear-gradient(135deg,#8b5cf6,#06b6d4)' : 'rgba(255,255,255,0.07)',
                  color: '#fff',
                  border: plan.highlight ? 'none' : '1px solid rgba(255,255,255,0.1)',
                  cursor: 'pointer',
                }} className="hover:opacity-90 transition-opacity">
                  {plan.cta}
                </button>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ══════════ TESTIMONIALS ══════════ */}
      <section id="الآراء" style={{ background: 'rgba(255,255,255,0.02)', borderTop: '1px solid rgba(255,255,255,0.06)', borderBottom: '1px solid rgba(255,255,255,0.06)', padding: '96px 24px' }}>
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p style={{ fontSize: 13, color: '#38bdf8', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 12 }}>آراء العملاء</p>
            <h2 style={{ fontSize: 'clamp(28px,4vw,44px)', fontWeight: 900 }}>ماذا يقول أصحاب المتاجر</h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {TESTIMONIALS.map(t => (
              <div key={t.name} style={{ borderRadius: 20, border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.03)', padding: 24 }}>
                {/* Stars */}
                <div style={{ display: 'flex', gap: 3, marginBottom: 16 }}>
                  {[...Array(5)].map((_, i) => (
                    <svg key={i} width={14} height={14} viewBox="0 0 24 24" fill="#fbbf24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></svg>
                  ))}
                </div>
                <p style={{ fontSize: 14, color: 'rgba(255,255,255,0.65)', lineHeight: 1.8, marginBottom: 20 }}>"{t.text}"</p>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div style={{ width: 40, height: 40, borderRadius: '50%', background: `linear-gradient(135deg, ${t.color.replace('from-','').replace(' to-','').split(' ').join(',')})`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, fontWeight: 800, flexShrink: 0 }}>
                    {t.avatar}
                  </div>
                  <div>
                    <p style={{ fontSize: 14, fontWeight: 700 }}>{t.name}</p>
                    <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)' }}>{t.role}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ══════════ FAQ ══════════ */}
      <section id="الأسئلة" className="py-24 px-6">
        <div className="max-w-2xl mx-auto">
          <div className="text-center mb-14">
            <p style={{ fontSize: 13, color: '#a78bfa', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 12 }}>الأسئلة الشائعة</p>
            <h2 style={{ fontSize: 'clamp(28px,4vw,40px)', fontWeight: 900 }}>لديك سؤال؟</h2>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {FAQS.map((faq, i) => (
              <div key={i} style={{ borderRadius: 16, border: '1px solid rgba(255,255,255,0.08)', background: openFaq === i ? 'rgba(139,92,246,0.06)' : 'rgba(255,255,255,0.02)', overflow: 'hidden', transition: 'all 0.2s' }}>
                <button
                  onClick={() => setOpenFaq(openFaq === i ? null : i)}
                  style={{ width: '100%', padding: '18px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', textAlign: 'right' }}
                >
                  <span style={{ fontSize: 15, fontWeight: 600, color: openFaq === i ? '#a78bfa' : '#fff' }}>{faq.q}</span>
                  <span style={{ color: 'rgba(255,255,255,0.4)', transition: 'transform 0.2s', transform: openFaq === i ? 'rotate(45deg)' : 'none', flexShrink: 0 }}>
                    <Icon d="M12 4v16m8-8H4" size={16} />
                  </span>
                </button>
                {openFaq === i && (
                  <div style={{ padding: '0 20px 18px', fontSize: 14, color: 'rgba(255,255,255,0.55)', lineHeight: 1.8 }}>
                    {faq.a}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ══════════ CTA ══════════ */}
      <section className="py-24 px-6">
        <div className="max-w-3xl mx-auto text-center">
          <div style={{ borderRadius: 28, border: '1px solid rgba(139,92,246,0.25)', background: 'linear-gradient(135deg, rgba(139,92,246,0.08), rgba(6,182,212,0.04))', padding: '64px 40px', position: 'relative', overflow: 'hidden', boxShadow: '0 0 80px rgba(139,92,246,0.1)' }}>
            <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)', width: 300, height: 300, background: 'radial-gradient(circle, rgba(139,92,246,0.12) 0%, transparent 70%)', borderRadius: '50%', pointerEvents: 'none' }} />
            <p style={{ fontSize: 13, color: '#a78bfa', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 16, position: 'relative' }}>ابدأ الآن</p>
            <h2 style={{ fontSize: 'clamp(28px,4vw,48px)', fontWeight: 900, marginBottom: 16, position: 'relative' }}>جاهز تحوّل متجرك؟</h2>
            <p style={{ color: 'rgba(255,255,255,0.5)', fontSize: 17, marginBottom: 36, lineHeight: 1.7, position: 'relative' }}>
              انضم لمئات المتاجر اللي تعمل بذكاء بينما أصحابها يرتاحون.
            </p>
            <button onClick={handleCTA} style={{ position: 'relative', background: 'linear-gradient(135deg,#8b5cf6,#06b6d4)', borderRadius: 14, padding: '16px 40px', fontSize: 17, fontWeight: 800, color: '#fff', boxShadow: '0 0 50px rgba(139,92,246,0.4)' }}
              className="hover:opacity-90 hover:scale-[1.02] transition-all flex items-center gap-2 mx-auto">
              <Icon d="M13 10V3L4 14h7v7l9-11h-7z" size={20} />
              ابدأ مجاناً — بدون بطاقة
            </button>
          </div>
        </div>
      </section>

      {/* ══════════ FOOTER ══════════ */}
      <footer style={{ borderTop: '1px solid rgba(255,255,255,0.06)', padding: '32px 24px' }}>
        <div className="max-w-6xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div style={{ width: 30, height: 30, borderRadius: 8, background: 'linear-gradient(135deg,#8b5cf6,#06b6d4)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Icon d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" size={14} className="text-white" />
            </div>
            <span style={{ fontWeight: 800, fontSize: 15 }}>سلّابوت</span>
          </div>
          <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.3)' }}>© ٢٠٢٥ سلّابوت — مساعد AI لمتاجر سلة</p>
          <button onClick={handleCTA} style={{ fontSize: 13, color: '#a78bfa', fontWeight: 600 }} className="hover:text-white transition-colors">
            تسجيل الدخول ←
          </button>
        </div>
      </footer>
    </div>
  )
}
