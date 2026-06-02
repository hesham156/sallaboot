import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, useScroll, useTransform, AnimatePresence } from 'framer-motion'
import { getToken, getIsSuper, getStoreId } from '../api'

/* ─────────────────────────────────────────
   Re-usable animation variants
───────────────────────────────────────── */
const fadeUp = {
  hidden: { opacity: 0, y: 32 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] } },
}
const fadeIn = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.5 } },
}
const stagger = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.09, delayChildren: 0.1 } },
}
const cardHover = {
  rest: { scale: 1, borderColor: 'rgba(255,255,255,0.08)' },
  hover: { scale: 1.02, borderColor: 'rgba(139,92,246,0.4)', transition: { duration: 0.2 } },
}

/* ─────────────────────────────────────────
   Tiny SVG icon
───────────────────────────────────────── */
function Icon({ d, size = 18, className = '' }: { d: string | string[]; size?: number; className?: string }) {
  const paths = Array.isArray(d) ? d : [d]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round"
      className={className}>
      {paths.map((p, i) => <path key={i} d={p} />)}
    </svg>
  )
}

/* ─────────────────────────────────────────
   Section wrapper with scroll entrance
───────────────────────────────────────── */
function Section({ children, className = '', id, style }: { children: React.ReactNode; className?: string; id?: string; style?: React.CSSProperties }) {
  return (
    <motion.section
      id={id}
      style={style}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, amount: 0.12 }}
      variants={stagger}
      className={className}
    >
      {children}
    </motion.section>
  )
}

/* ─────────────────────────────────────────
   Data
───────────────────────────────────────── */
const MARQUEE_ITEMS = ['سلة', 'زيد', 'إكسباند', 'نقودي', 'شاهد', 'مدفوعات', 'نون', 'أمازون', 'جاهز', 'تجار']

const STATS = [
  { value: '+٥٠٠', label: 'متجر نشط' },
  { value: '٩٧٪', label: 'رضا العملاء' },
  { value: '٢٤/٧', label: 'متاح دائماً' },
  { value: '<٢ث', label: 'زمن الرد' },
]

const BENTO = [
  {
    size: 'large',  // spans 2 cols
    icon: 'M8 10h.01M12 10h.01M16 10h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z',
    title: 'دردشة ذكية تفهم العربية',
    desc: 'بوت يفهم اللهجات المختلفة ويرد بأسلوب طبيعي يشبه موظف الخدمة الحقيقي — بلا توقف.',
    accent: '#8b5cf6',
    glow: 'rgba(139,92,246,0.12)',
    badge: 'AI محادثة',
  },
  {
    size: 'normal',
    icon: 'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4',
    title: 'مزامنة تلقائية مع سلة',
    desc: 'يتصل مباشرةً بـ API سلة ويحدّث نفسه عند أي تغيير.',
    accent: '#06b6d4',
    glow: 'rgba(6,182,212,0.12)',
    badge: null,
  },
  {
    size: 'normal',
    icon: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z',
    title: 'تحليلات فورية',
    desc: 'تقارير مفصّلة عن المحادثات والتحويلات والأسئلة الأكثر تكراراً.',
    accent: '#34d399',
    glow: 'rgba(52,211,153,0.12)',
    badge: null,
  },
  {
    size: 'normal',
    icon: 'M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z',
    title: 'تدريب مخصص للمتجر',
    desc: 'علّمه شخصية متجرك وسياساتك وأسلوبك الفريد.',
    accent: '#f59e0b',
    glow: 'rgba(245,158,11,0.12)',
    badge: null,
  },
  {
    size: 'large',  // spans 2 cols
    icon: 'M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z',
    title: 'استرداد السلات المتروكة',
    desc: 'يتابع العملاء الذين تركوا الطلب ويُعيدهم بأسلوب ذكي يحوّلهم لمبيعات حقيقية وقابلة للقياس.',
    accent: '#f43f5e',
    glow: 'rgba(244,63,94,0.12)',
    badge: 'الأعلى تأثيراً',
  },
  {
    size: 'normal',
    icon: 'M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z',
    title: 'عزل تام وأمان',
    desc: 'كل متجر في بيئة مستقلة محمية بتشفير SSL كامل.',
    accent: '#64748b',
    glow: 'rgba(100,116,139,0.1)',
    badge: null,
  },
]

const PRICING = [
  {
    name: 'مجاني', price: '٠', period: 'دائماً',
    desc: 'للمتاجر الصغيرة',
    features: ['بوت AI أساسي', '٢٠٠ رسالة/شهر', 'مزامنة المنتجات', 'دعم بريد إلكتروني'],
    cta: 'ابدأ مجاناً', highlight: false,
  },
  {
    name: 'برو', price: '٩٩', period: 'ريال/شهر',
    desc: 'للمتاجر الجادة',
    features: ['رسائل غير محدودة', 'تحليلات متقدمة', 'تدريب مخصص', 'سلات متروكة', 'دعم ٢٤/٧'],
    cta: 'جرّب ٧ أيام مجاناً', highlight: true, badge: 'الأكثر شيوعاً',
  },
  {
    name: 'مؤسسي', price: '٢٩٩', period: 'ريال/شهر',
    desc: 'للشركات والمتاجر الكبيرة',
    features: ['كل مزايا برو', 'متاجر متعددة', 'API مخصص', 'مدير حساب', 'SLA مضمون'],
    cta: 'تواصل معنا', highlight: false,
  },
]

const TESTIMONIALS = [
  { name: 'أحمد السيد', role: 'متجر طباعة — جدة', text: 'وفّر عليّ ساعات يومياً في الرد على أسئلة العملاء. المبيعات ارتفعت ٣٠٪ خلال الشهر الأول.', init: 'أ', color: '#8b5cf6' },
  { name: 'سارة المطيري', role: 'متجر إلكتروني — الرياض', text: 'كنت أفكر في توظيف موظف للرد. البوت حل المشكلة بعُشر التكلفة وبأسلوب أفضل بكثير.', init: 'س', color: '#06b6d4' },
  { name: 'محمد العتيبي', role: 'مستلزمات — الدمام', text: 'المزامنة مع سلة احترافية جداً. البوت يعرف كل منتج وأسعاره ويقترح البديل لما ينتهي.', init: 'م', color: '#34d399' },
]

const FAQS = [
  { q: 'هل يعمل مع أي متجر سلة؟', a: 'نعم، يعمل مع جميع متاجر سلة بدون استثناء. تحتاج فقط Access Token لربط المتجر.' },
  { q: 'كيف يتعلم البوت منتجاتي؟', a: 'يتصل مباشرةً بـ API سلة ويسحب المنتجات والأسعار والتصنيفات تلقائياً وبشكل دوري.' },
  { q: 'هل بيانات عملائي آمنة؟', a: 'كل متجر معزول تماماً في بيئة مستقلة مع تشفير SSL الكامل لجميع البيانات.' },
  { q: 'ماذا يحدث لو لم يعرف البوت الجواب؟', a: 'يُخبر العميل بأدب ويسجّل السؤال لمراجعتك وتحسين البوت مستقبلاً.' },
  { q: 'هل أقدر أخصص أسلوب البوت؟', a: 'بالكامل — تحكم في الشخصية والأسلوب والأسئلة الشائعة والردود الافتراضية.' },
]

/* ─────────────────────────────────────────
   Main Component
───────────────────────────────────────── */
export default function Landing() {
  const navigate = useNavigate()
  const [openFaq, setOpenFaq] = useState<number | null>(null)
  const [billingYearly, setBillingYearly] = useState(false)
  const [testimonialIdx, setTestimonialIdx] = useState(0)
  const heroRef = useRef<HTMLDivElement>(null)

  // Navbar scroll effect
  const { scrollY } = useScroll()
  const navBg = useTransform(scrollY, [0, 60], ['rgba(7,7,26,0)', 'rgba(7,7,26,0.92)'])
  const navBorder = useTransform(scrollY, [0, 60], ['rgba(255,255,255,0)', 'rgba(255,255,255,0.07)'])

  function handleCTA() {
    const token = getToken()
    if (!token) { navigate('/login'); return }
    navigate(getIsSuper() ? '/admin' : `/store/${getStoreId()}`)
  }

  const C = { // brand colors
    bg: '#07071a',
    primary: '#8b5cf6',
    secondary: '#06b6d4',
    accent: '#34d399',
    text: '#ffffff',
    muted: 'rgba(255,255,255,0.5)',
    card: 'rgba(255,255,255,0.03)',
    border: 'rgba(255,255,255,0.08)',
  }

  return (
    <div style={{ minHeight: '100vh', background: C.bg, color: C.text, overflowX: 'hidden' }} dir="rtl">

      {/* ── Ambient glow orbs ── */}
      <div aria-hidden className="fixed inset-0 pointer-events-none overflow-hidden">
        <div style={{ position:'absolute', top:'-15%', right:'25%', width:700, height:700, background:`radial-gradient(circle, rgba(139,92,246,0.1) 0%, transparent 65%)`, borderRadius:'50%' }}/>
        <div style={{ position:'absolute', top:'35%', left:'-5%', width:500, height:500, background:`radial-gradient(circle, rgba(6,182,212,0.07) 0%, transparent 65%)`, borderRadius:'50%' }}/>
        <div style={{ position:'absolute', bottom:'5%', right:'5%', width:400, height:400, background:`radial-gradient(circle, rgba(139,92,246,0.06) 0%, transparent 65%)`, borderRadius:'50%' }}/>
      </div>

      {/* ══════════════════════════════
          NAVBAR
      ══════════════════════════════ */}
      <motion.nav
        style={{ background: navBg, borderBottom: `1px solid`, borderColor: navBorder, backdropFilter:'blur(20px)', position:'sticky', top:0, zIndex:50 }}
      >
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          {/* Logo */}
          <motion.div className="flex items-center gap-2.5" whileHover={{ scale: 1.02 }}>
            <div style={{ width:34, height:34, borderRadius:10, background:`linear-gradient(135deg, ${C.primary}, ${C.secondary})`, display:'flex', alignItems:'center', justifyContent:'center', boxShadow:`0 0 20px rgba(139,92,246,0.4)` }}>
              <Icon d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" size={15} className="text-white" />
            </div>
            <span style={{ fontWeight:900, fontSize:18, letterSpacing:'-0.02em' }}>سلّابوت</span>
          </motion.div>

          {/* Links */}
          <div className="hidden md:flex items-center gap-7">
            {[['المزايا','#features'],['الأسعار','#pricing'],['الآراء','#testimonials'],['الأسئلة','#faq']].map(([label, href]) => (
              <a key={href} href={href}
                style={{ color: C.muted, fontSize:14, fontWeight:500, textDecoration:'none' }}
                className="hover:text-white transition-colors duration-200">{label}</a>
            ))}
          </div>

          {/* CTAs */}
          <div className="flex items-center gap-2">
            <button onClick={handleCTA}
              style={{ color: C.muted, fontSize:14, fontWeight:600, padding:'8px 14px', background:'none', border:'none', cursor:'pointer' }}
              className="hover:text-white transition-colors">
              دخول
            </button>
            <motion.button onClick={handleCTA} whileHover={{ scale:1.04 }} whileTap={{ scale:0.97 }}
              style={{ background:`linear-gradient(135deg, ${C.primary}, ${C.secondary})`, borderRadius:10, padding:'9px 20px', fontSize:14, fontWeight:700, color:'#fff', border:'none', cursor:'pointer', boxShadow:`0 0 24px rgba(139,92,246,0.3)` }}>
              ابدأ مجاناً
            </motion.button>
          </div>
        </div>
      </motion.nav>

      {/* ══════════════════════════════
          HERO
      ══════════════════════════════ */}
      <section ref={heroRef} className="relative px-6 pt-20 pb-16">
        <div className="max-w-6xl mx-auto">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">

            {/* Left — Text */}
            <motion.div initial="hidden" animate="visible" variants={stagger} className="space-y-6">
              {/* Badge */}
              <motion.div variants={fadeUp}>
                <span style={{ display:'inline-flex', alignItems:'center', gap:8, padding:'6px 16px', borderRadius:999, border:`1px solid rgba(139,92,246,0.35)`, background:'rgba(139,92,246,0.1)', fontSize:13, color:'#c4b5fd', fontWeight:600 }}>
                  <span style={{ width:6, height:6, borderRadius:'50%', background:'#a78bfa', display:'inline-block', animation:'pulse 2s infinite' }}/>
                  مدعوم بـ GPT-4 و Claude Sonnet
                </span>
              </motion.div>

              {/* Headline */}
              <motion.h1 variants={fadeUp}
                style={{ fontSize:'clamp(38px,5.5vw,68px)', fontWeight:900, lineHeight:1.08, letterSpacing:'-0.03em' }}>
                بوت يبيع لك
                <br />
                <span style={{ background:`linear-gradient(90deg, #a78bfa 0%, #38bdf8 50%, #34d399 100%)`, WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>
                  وأنت نايم
                </span>
              </motion.h1>

              {/* Sub */}
              <motion.p variants={fadeUp}
                style={{ fontSize:17, color: C.muted, lineHeight:1.75, maxWidth:460 }}>
                مساعد AI يتحدث مع عملاء متجرك على سلة، يشرح المنتجات، يتابع الطلبات،
                ويُحوّل الاستفسارات لمبيعات — على مدار الساعة بدون تدخّل منك.
              </motion.p>

              {/* CTAs */}
              <motion.div variants={fadeUp} className="flex items-center gap-3 flex-wrap">
                <motion.button onClick={handleCTA} whileHover={{ scale:1.03 }} whileTap={{ scale:0.97 }}
                  style={{ background:`linear-gradient(135deg, ${C.primary}, ${C.secondary})`, borderRadius:14, padding:'14px 32px', fontSize:16, fontWeight:800, color:'#fff', border:'none', cursor:'pointer', boxShadow:`0 0 40px rgba(139,92,246,0.35)`, display:'flex', alignItems:'center', gap:8 }}>
                  <Icon d="M13 10V3L4 14h7v7l9-11h-7z" size={18} />
                  ابدأ مجاناً — بدون بطاقة
                </motion.button>
                <motion.button onClick={handleCTA} whileHover={{ scale:1.02 }}
                  style={{ borderRadius:14, padding:'14px 24px', fontSize:16, fontWeight:700, color:'rgba(255,255,255,0.8)', border:`1px solid ${C.border}`, background:'rgba(255,255,255,0.04)', cursor:'pointer', display:'flex', alignItems:'center', gap:8 }}>
                  <Icon d="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" size={18} />
                  مشاهدة العرض
                </motion.button>
              </motion.div>

              {/* Social proof */}
              <motion.div variants={fadeUp} className="flex items-center gap-3 pt-2">
                <div className="flex -space-x-2 space-x-reverse">
                  {['أ','س','م','خ','ن'].map((l,i) => (
                    <div key={i} style={{ width:34, height:34, borderRadius:'50%', background:`hsl(${i*60+240},60%,55%)`, border:`2px solid ${C.bg}`, display:'flex', alignItems:'center', justifyContent:'center', fontSize:12, fontWeight:700 }}>{l}</div>
                  ))}
                </div>
                <div>
                  <div className="flex gap-0.5">
                    {[...Array(5)].map((_,i)=>(
                      <svg key={i} width={13} height={13} viewBox="0 0 24 24" fill="#fbbf24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
                    ))}
                  </div>
                  <p style={{ fontSize:12, color: C.muted, marginTop:2 }}>+٥٠٠ متجر يثق بسلّابوت</p>
                </div>
              </motion.div>
            </motion.div>

            {/* Right — Chat mockup */}
            <motion.div initial={{ opacity:0, x:-40 }} animate={{ opacity:1, x:0 }} transition={{ duration:0.7, delay:0.2, ease:[0.22,1,0.36,1] }}
              className="relative flex justify-center">

              {/* Floating stat badges */}
              <motion.div initial={{ opacity:0, y:20 }} animate={{ opacity:1, y:0 }} transition={{ delay:0.7 }}
                style={{ position:'absolute', top:-16, right:16, background:'rgba(255,255,255,0.06)', backdropFilter:'blur(16px)', border:`1px solid ${C.border}`, borderRadius:14, padding:'10px 16px', zIndex:10 }}>
                <p style={{ fontSize:11, color:C.muted, marginBottom:2 }}>رسائل اليوم</p>
                <p style={{ fontSize:20, fontWeight:900, color:'#a78bfa' }}>١٢٤</p>
              </motion.div>

              <motion.div initial={{ opacity:0, y:20 }} animate={{ opacity:1, y:0 }} transition={{ delay:0.9 }}
                style={{ position:'absolute', bottom:32, left:-8, background:'rgba(52,211,153,0.12)', backdropFilter:'blur(16px)', border:`1px solid rgba(52,211,153,0.25)`, borderRadius:14, padding:'10px 16px', zIndex:10 }}>
                <p style={{ fontSize:11, color:C.muted, marginBottom:2 }}>تحويل اليوم</p>
                <p style={{ fontSize:20, fontWeight:900, color:'#34d399' }}>٨٧٪</p>
              </motion.div>

              {/* Chat window */}
              <div style={{ width:'100%', maxWidth:420, borderRadius:22, border:`1px solid rgba(255,255,255,0.1)`, background:'rgba(255,255,255,0.03)', backdropFilter:'blur(24px)', overflow:'hidden', boxShadow:`0 40px 80px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.05)` }}>
                {/* Header */}
                <div style={{ padding:'12px 16px', borderBottom:`1px solid rgba(255,255,255,0.06)`, display:'flex', alignItems:'center', justifyContent:'space-between', background:'rgba(255,255,255,0.02)' }}>
                  <div style={{ display:'flex', alignItems:'center', gap:10 }}>
                    <div style={{ width:32, height:32, borderRadius:'50%', background:`linear-gradient(135deg,${C.primary},${C.secondary})`, display:'flex', alignItems:'center', justifyContent:'center' }}>
                      <Icon d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" size={14} className="text-white" />
                    </div>
                    <div>
                      <p style={{ fontSize:12, fontWeight:700 }}>مساعد متجر النور للطباعة</p>
                      <p style={{ fontSize:10, color:'#34d399', display:'flex', alignItems:'center', gap:4 }}>
                        <span style={{ width:5, height:5, background:'#34d399', borderRadius:'50%', display:'inline-block' }}/>
                        متصل الآن
                      </p>
                    </div>
                  </div>
                  <div style={{ display:'flex', gap:6 }}>
                    {['#ef4444','#f59e0b','#34d399'].map(c=>(
                      <div key={c} style={{ width:10, height:10, borderRadius:'50%', background:c, opacity:0.7 }}/>
                    ))}
                  </div>
                </div>

                {/* Messages */}
                <div style={{ padding:16, display:'flex', flexDirection:'column', gap:10, minHeight:260 }}>
                  {[
                    { from:'bot', text:'أهلاً! كيف أقدر أساعدك اليوم؟ 😊' },
                    { from:'user', text:'عندكم طباعة على أكواب؟' },
                    { from:'bot', text:'نعم! عندنا:\n• كوب سيراميك ٣٣٠ml — ٢٥ ريال\n• كوب حراري ٤٥٠ml — ٤٥ ريال\n• كوب زجاجي فاخر — ٦٥ ريال\nالكل طباعة ملونة عالية الجودة 🎨' },
                    { from:'user', text:'ما هو أقل كمية؟' },
                    { from:'bot', text:'الحد الأدنى ١٠ قطع لكل تصميم. مع خصم ١٥٪ على طلبات +٥٠ قطعة 🎁' },
                  ].map((m, i) => (
                    <motion.div key={i} initial={{ opacity:0, y:8 }} animate={{ opacity:1, y:0 }} transition={{ delay: 0.4 + i*0.1 }}
                      style={{ display:'flex', justifyContent: m.from==='user' ? 'flex-start' : 'flex-end' }}>
                      <div style={{
                        maxWidth:'78%', padding:'10px 14px',
                        borderRadius: m.from==='bot' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                        background: m.from==='bot' ? `linear-gradient(135deg, rgba(139,92,246,0.2), rgba(6,182,212,0.12))` : 'rgba(255,255,255,0.07)',
                        border: `1px solid ${m.from==='bot' ? 'rgba(139,92,246,0.2)' : 'rgba(255,255,255,0.07)'}`,
                        fontSize:13, color:'#e2e8f0', lineHeight:1.65, whiteSpace:'pre-line', textAlign:'right',
                      }}>
                        {m.text}
                      </div>
                    </motion.div>
                  ))}
                  {/* Typing indicator */}
                  <motion.div initial={{ opacity:0 }} animate={{ opacity:1 }} transition={{ delay:1.4 }}
                    style={{ display:'flex', alignItems:'center', gap:4, padding:'6px 12px', borderRadius:12, background:'rgba(139,92,246,0.08)', border:'1px solid rgba(139,92,246,0.15)', width:'fit-content' }}>
                    {[0,1,2].map(i=>(
                      <motion.span key={i} animate={{ y:[0,-4,0] }} transition={{ repeat:Infinity, duration:0.8, delay:i*0.15 }}
                        style={{ width:5, height:5, borderRadius:'50%', background:'#a78bfa', display:'block' }}/>
                    ))}
                  </motion.div>
                </div>

                {/* Input bar */}
                <div style={{ padding:'10px 16px', borderTop:`1px solid rgba(255,255,255,0.06)` }}>
                  <div style={{ borderRadius:12, border:`1px solid rgba(255,255,255,0.08)`, background:'rgba(255,255,255,0.04)', padding:'9px 14px', display:'flex', alignItems:'center', justifyContent:'space-between', gap:8 }}>
                    <span style={{ fontSize:12, color:'rgba(255,255,255,0.25)' }}>اكتب رسالتك...</span>
                    <motion.div whileHover={{ scale:1.1 }} style={{ width:28, height:28, borderRadius:8, background:`linear-gradient(135deg,${C.primary},${C.secondary})`, display:'flex', alignItems:'center', justifyContent:'center', cursor:'pointer', flexShrink:0 }}>
                      <Icon d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" size={13} className="text-white" />
                    </motion.div>
                  </div>
                </div>
              </div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* ══════════════════════════════
          MARQUEE
      ══════════════════════════════ */}
      <div style={{ borderTop:`1px solid ${C.border}`, borderBottom:`1px solid ${C.border}`, padding:'18px 0', overflow:'hidden', background:'rgba(255,255,255,0.015)' }}>
        <motion.div
          animate={{ x: ['0%', '-50%'] }}
          transition={{ repeat: Infinity, duration: 18, ease: 'linear' }}
          style={{ display:'flex', gap:56, width:'max-content' }}
        >
          {[...MARQUEE_ITEMS, ...MARQUEE_ITEMS].map((item, i) => (
            <div key={i} style={{ display:'flex', alignItems:'center', gap:10, whiteSpace:'nowrap', color:'rgba(255,255,255,0.35)', fontSize:15, fontWeight:600 }}>
              <span style={{ width:6, height:6, borderRadius:'50%', background:C.primary, display:'inline-block', opacity:0.6 }}/>
              {item}
            </div>
          ))}
        </motion.div>
      </div>

      {/* ══════════════════════════════
          STATS / ABOUT
      ══════════════════════════════ */}
      <Section className="py-24 px-6">
        <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
          {/* Left */}
          <div className="space-y-8">
            <motion.div variants={fadeUp}>
              <p style={{ fontSize:13, color:C.primary, fontWeight:700, letterSpacing:'0.12em', textTransform:'uppercase', marginBottom:12 }}>الأرقام تتكلم</p>
              <h2 style={{ fontSize:'clamp(28px,3.5vw,44px)', fontWeight:900, lineHeight:1.15, letterSpacing:'-0.02em' }}>
                موثوق من مئات
                <br />المتاجر في المملكة
              </h2>
              <p style={{ color:C.muted, fontSize:16, lineHeight:1.75, marginTop:16, maxWidth:420 }}>
                من متاجر الطباعة إلى الأزياء والإلكترونيات — سلّابوت يعمل مع كل أنواع متاجر سلة.
              </p>
            </motion.div>

            <motion.div variants={stagger} className="grid grid-cols-2 gap-5">
              {STATS.map(s => (
                <motion.div key={s.value} variants={fadeUp}
                  style={{ borderRadius:18, border:`1px solid ${C.border}`, background:C.card, padding:'20px 22px' }}>
                  <p style={{ fontSize:36, fontWeight:900, background:`linear-gradient(90deg,#a78bfa,#38bdf8)`, WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent', lineHeight:1 }}>{s.value}</p>
                  <p style={{ fontSize:13, color:C.muted, marginTop:8, fontWeight:500 }}>{s.label}</p>
                </motion.div>
              ))}
            </motion.div>
          </div>

          {/* Right — visual card */}
          <motion.div variants={fadeIn}
            style={{ borderRadius:24, border:`1px solid rgba(139,92,246,0.2)`, background:'linear-gradient(135deg, rgba(139,92,246,0.08), rgba(6,182,212,0.04))', padding:32, position:'relative', overflow:'hidden' }}>
            <div style={{ position:'absolute', top:0, right:0, width:200, height:200, background:'radial-gradient(circle, rgba(139,92,246,0.15) 0%, transparent 70%)', borderRadius:'50%' }}/>
            <div style={{ position:'relative' }}>
              <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom:24 }}>
                <div style={{ width:44, height:44, borderRadius:14, background:`linear-gradient(135deg,${C.primary},${C.secondary})`, display:'flex', alignItems:'center', justifyContent:'center' }}>
                  <Icon d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" size={22} className="text-white" />
                </div>
                <div>
                  <p style={{ fontWeight:700, fontSize:15 }}>تحويل ناجح</p>
                  <p style={{ fontSize:12, color:C.muted }}>منذ ٣ دقائق</p>
                </div>
              </div>
              <p style={{ fontSize:24, fontWeight:900, marginBottom:4 }}>+٣٢ طلب جديد</p>
              <p style={{ fontSize:13, color:C.muted, lineHeight:1.7, marginBottom:24 }}>
                تمّ إنشاؤها من محادثات البوت خلال آخر ٢٤ ساعة بدون أي تدخّل يدوي.
              </p>
              <div style={{ display:'flex', flexDirection:'column', gap:10 }}>
                {[
                  { label:'أكواب مطبوعة ×٢٠', val:'٥٠٠ ريال', pct:85 },
                  { label:'بطاقات شخصية ×١٠٠', val:'٨٠ ريال', pct:40 },
                  { label:'كروت هدايا ×٥٠', val:'١٢٠ ريال', pct:60 },
                ].map(item=>(
                  <div key={item.label}>
                    <div style={{ display:'flex', justifyContent:'space-between', marginBottom:5, fontSize:12 }}>
                      <span style={{ color:C.muted }}>{item.label}</span>
                      <span style={{ color:'#34d399', fontWeight:700 }}>{item.val}</span>
                    </div>
                    <div style={{ height:4, borderRadius:99, background:'rgba(255,255,255,0.07)', overflow:'hidden' }}>
                      <motion.div initial={{ width:0 }} whileInView={{ width:`${item.pct}%` }} viewport={{ once:true }} transition={{ duration:0.8, delay:0.2 }}
                        style={{ height:'100%', borderRadius:99, background:`linear-gradient(90deg,${C.primary},${C.secondary})` }}/>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </motion.div>
        </div>
      </Section>

      {/* ══════════════════════════════
          BENTO FEATURES
      ══════════════════════════════ */}
      <Section id="features" className="py-24 px-6">
        <div className="max-w-6xl mx-auto">
          <motion.div variants={fadeUp} className="text-center mb-14">
            <p style={{ fontSize:13, color:C.primary, fontWeight:700, letterSpacing:'0.12em', textTransform:'uppercase', marginBottom:12 }}>المزايا</p>
            <h2 style={{ fontSize:'clamp(28px,3.5vw,44px)', fontWeight:900, letterSpacing:'-0.02em', marginBottom:14 }}>كل ما تحتاجه في مكان واحد</h2>
            <p style={{ color:C.muted, fontSize:16, maxWidth:480, margin:'0 auto' }}>منظومة متكاملة مصممة خصيصاً لمتاجر سلة</p>
          </motion.div>

          <motion.div variants={stagger} className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {BENTO.map((f, i) => (
              <motion.div key={i} variants={fadeUp}
                whileHover={{ scale:1.02, y:-4 }}
                className={f.size === 'large' ? 'lg:col-span-2' : ''}
                style={{ borderRadius:22, border:`1px solid ${C.border}`, background:C.card, padding:28, position:'relative', overflow:'hidden', cursor:'default', boxShadow:`0 0 40px ${f.glow}` }}
                transition={{ duration:0.2 }}>
                {/* Glow blob */}
                <div style={{ position:'absolute', top:-30, right:-30, width:120, height:120, background:`radial-gradient(circle, ${f.glow.replace('0.12','0.3')} 0%, transparent 70%)`, borderRadius:'50%', pointerEvents:'none' }}/>
                {/* Badge */}
                {f.badge && (
                  <div style={{ position:'absolute', top:16, left:16, background:`${f.accent}22`, border:`1px solid ${f.accent}44`, borderRadius:999, padding:'3px 10px', fontSize:11, fontWeight:700, color:f.accent }}>
                    {f.badge}
                  </div>
                )}
                {/* Icon */}
                <div style={{ position:'relative', width:44, height:44, borderRadius:14, background:`${f.accent}18`, border:`1px solid ${f.accent}33`, display:'flex', alignItems:'center', justifyContent:'center', marginBottom:16, color:f.accent }}>
                  <Icon d={f.icon} size={20} />
                </div>
                <h3 style={{ fontSize:16, fontWeight:700, marginBottom:10, position:'relative' }}>{f.title}</h3>
                <p style={{ fontSize:14, color:C.muted, lineHeight:1.7, position:'relative' }}>{f.desc}</p>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </Section>

      {/* ══════════════════════════════
          PRICING
      ══════════════════════════════ */}
      <Section id="pricing" style={{ background:'rgba(255,255,255,0.015)', borderTop:`1px solid ${C.border}`, borderBottom:`1px solid ${C.border}` }} className="py-24 px-6">
        <div className="max-w-5xl mx-auto">
          <motion.div variants={fadeUp} className="text-center mb-12">
            <p style={{ fontSize:13, color:C.primary, fontWeight:700, letterSpacing:'0.12em', textTransform:'uppercase', marginBottom:12 }}>الأسعار</p>
            <h2 style={{ fontSize:'clamp(28px,3.5vw,44px)', fontWeight:900, letterSpacing:'-0.02em', marginBottom:14 }}>بسيط وشفاف — بدون مفاجآت</h2>

            {/* Toggle */}
            <div style={{ display:'inline-flex', alignItems:'center', gap:12, background:'rgba(255,255,255,0.05)', border:`1px solid ${C.border}`, borderRadius:999, padding:'6px 8px', marginTop:8 }}>
              {['شهري','سنوي'].map((l,i) => (
                <motion.button key={l} onClick={() => setBillingYearly(i===1)}
                  style={{ borderRadius:999, padding:'7px 20px', fontSize:14, fontWeight:700, cursor:'pointer', border:'none', color: (billingYearly===false && i===0)||(billingYearly===true && i===1) ? '#fff' : C.muted, background:(billingYearly===false && i===0)||(billingYearly===true && i===1) ? `linear-gradient(135deg,${C.primary},${C.secondary})` : 'transparent' }}
                  layout>
                  {l}
                  {i===1 && <span style={{ fontSize:11, marginRight:6, color:'#34d399' }}>وفّر ١٧٪</span>}
                </motion.button>
              ))}
            </div>
          </motion.div>

          <motion.div variants={stagger} className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {PRICING.map((plan, i) => (
              <motion.div key={i} variants={fadeUp} whileHover={{ y:-6 }}
                style={{ borderRadius:24, border:`1px solid ${plan.highlight ? 'rgba(139,92,246,0.5)' : C.border}`, background: plan.highlight ? 'linear-gradient(135deg, rgba(139,92,246,0.1), rgba(6,182,212,0.05))' : C.card, padding:32, position:'relative', boxShadow: plan.highlight ? `0 0 60px rgba(139,92,246,0.15)` : 'none' }}>
                {plan.badge && (
                  <div style={{ position:'absolute', top:-13, right:28, background:`linear-gradient(90deg,${C.primary},${C.secondary})`, borderRadius:999, padding:'4px 14px', fontSize:11, fontWeight:700, color:'#fff' }}>
                    {plan.badge}
                  </div>
                )}
                <p style={{ fontSize:14, color:C.muted, marginBottom:8 }}>{plan.name}</p>
                <div style={{ display:'flex', alignItems:'baseline', gap:6, marginBottom:8 }}>
                  <span style={{ fontSize:46, fontWeight:900, color: plan.highlight ? '#a78bfa' : '#fff', letterSpacing:'-0.03em' }}>
                    {billingYearly && plan.price !== '٠' ? String(Math.round(parseInt(plan.price.replace(/[٠-٩]/g, d => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)))) * 0.83)) : plan.price}
                  </span>
                  <span style={{ fontSize:13, color:'rgba(255,255,255,0.35)' }}>ريال/{plan.period === 'دائماً' ? 'دائماً' : 'شهر'}</span>
                </div>
                <p style={{ fontSize:13, color:C.muted, marginBottom:24, lineHeight:1.6 }}>{plan.desc}</p>
                <ul style={{ display:'flex', flexDirection:'column', gap:10, marginBottom:28 }}>
                  {plan.features.map(f => (
                    <li key={f} style={{ display:'flex', alignItems:'center', gap:10, fontSize:14, color:'rgba(255,255,255,0.75)' }}>
                      <div style={{ width:18, height:18, borderRadius:'50%', background:'rgba(52,211,153,0.15)', border:'1px solid rgba(52,211,153,0.3)', display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0 }}>
                        <Icon d="M5 13l4 4L19 7" size={11} className="text-emerald-400" />
                      </div>
                      {f}
                    </li>
                  ))}
                </ul>
                <motion.button onClick={handleCTA} whileHover={{ scale:1.02 }} whileTap={{ scale:0.97 }}
                  style={{ width:'100%', padding:'13px', borderRadius:13, fontSize:15, fontWeight:700, background: plan.highlight ? `linear-gradient(135deg,${C.primary},${C.secondary})` : 'rgba(255,255,255,0.07)', color:'#fff', border: plan.highlight ? 'none' : `1px solid ${C.border}`, cursor:'pointer' }}>
                  {plan.cta}
                </motion.button>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </Section>

      {/* ══════════════════════════════
          TESTIMONIALS
      ══════════════════════════════ */}
      <Section id="testimonials" className="py-24 px-6">
        <div className="max-w-5xl mx-auto">
          <motion.div variants={fadeUp} className="text-center mb-14">
            <p style={{ fontSize:13, color:C.secondary, fontWeight:700, letterSpacing:'0.12em', textTransform:'uppercase', marginBottom:12 }}>آراء العملاء</p>
            <h2 style={{ fontSize:'clamp(28px,3.5vw,44px)', fontWeight:900, letterSpacing:'-0.02em' }}>ماذا يقول أصحاب المتاجر</h2>
          </motion.div>

          <motion.div variants={stagger} className="grid grid-cols-1 md:grid-cols-3 gap-5 mb-8">
            {TESTIMONIALS.map((t, i) => (
              <motion.div key={i} variants={fadeUp} whileHover={{ y:-4 }}
                style={{ borderRadius:22, border:`1px solid ${C.border}`, background:C.card, padding:26 }}>
                <div style={{ display:'flex', gap:3, marginBottom:14 }}>
                  {[...Array(5)].map((_,j)=>(
                    <svg key={j} width={14} height={14} viewBox="0 0 24 24" fill="#fbbf24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
                  ))}
                </div>
                <p style={{ fontSize:14, color:'rgba(255,255,255,0.65)', lineHeight:1.8, marginBottom:20 }}>"{t.text}"</p>
                <div style={{ display:'flex', alignItems:'center', gap:12 }}>
                  <div style={{ width:38, height:38, borderRadius:'50%', background:t.color, display:'flex', alignItems:'center', justifyContent:'center', fontSize:15, fontWeight:800, flexShrink:0 }}>{t.init}</div>
                  <div>
                    <p style={{ fontSize:14, fontWeight:700 }}>{t.name}</p>
                    <p style={{ fontSize:12, color:C.muted }}>{t.role}</p>
                  </div>
                </div>
              </motion.div>
            ))}
          </motion.div>

          {/* Dots */}
          <div style={{ display:'flex', justifyContent:'center', gap:8 }}>
            {TESTIMONIALS.map((_,i)=>(
              <button key={i} onClick={() => setTestimonialIdx(i)} style={{ width: i===testimonialIdx ? 24 : 8, height:8, borderRadius:999, background: i===testimonialIdx ? C.primary : 'rgba(255,255,255,0.2)', border:'none', cursor:'pointer', transition:'all 0.3s' }}/>
            ))}
          </div>
        </div>
      </Section>

      {/* ══════════════════════════════
          FAQ
      ══════════════════════════════ */}
      <Section id="faq" style={{ background:'rgba(255,255,255,0.015)', borderTop:`1px solid ${C.border}` }} className="py-24 px-6">
        <div className="max-w-2xl mx-auto">
          <motion.div variants={fadeUp} className="text-center mb-14">
            <p style={{ fontSize:13, color:C.primary, fontWeight:700, letterSpacing:'0.12em', textTransform:'uppercase', marginBottom:12 }}>الأسئلة الشائعة</p>
            <h2 style={{ fontSize:'clamp(26px,3.5vw,40px)', fontWeight:900, letterSpacing:'-0.02em' }}>لديك سؤال؟</h2>
          </motion.div>

          <motion.div variants={stagger} style={{ display:'flex', flexDirection:'column', gap:8 }}>
            {FAQS.map((faq, i) => (
              <motion.div key={i} variants={fadeUp}
                style={{ borderRadius:16, border:`1px solid ${openFaq===i ? 'rgba(139,92,246,0.35)' : C.border}`, background: openFaq===i ? 'rgba(139,92,246,0.05)' : C.card, overflow:'hidden', transition:'border-color 0.2s, background 0.2s' }}>
                <button onClick={() => setOpenFaq(openFaq===i ? null : i)}
                  style={{ width:'100%', padding:'18px 22px', display:'flex', alignItems:'center', justifyContent:'space-between', textAlign:'right', background:'none', border:'none', cursor:'pointer', color:'#fff' }}>
                  <span style={{ fontSize:15, fontWeight:600, color: openFaq===i ? '#c4b5fd' : '#fff' }}>{faq.q}</span>
                  <motion.span animate={{ rotate: openFaq===i ? 45 : 0 }} style={{ color:C.muted, flexShrink:0 }}>
                    <Icon d="M12 4v16m8-8H4" size={16} />
                  </motion.span>
                </button>
                <AnimatePresence>
                  {openFaq===i && (
                    <motion.div initial={{ height:0, opacity:0 }} animate={{ height:'auto', opacity:1 }} exit={{ height:0, opacity:0 }} transition={{ duration:0.25 }}
                      style={{ overflow:'hidden' }}>
                      <p style={{ padding:'0 22px 18px', fontSize:14, color:C.muted, lineHeight:1.8 }}>{faq.a}</p>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </Section>

      {/* ══════════════════════════════
          CTA BANNER
      ══════════════════════════════ */}
      <Section className="py-20 px-6">
        <div className="max-w-3xl mx-auto">
          <motion.div variants={fadeUp}
            style={{ borderRadius:28, border:`1px solid rgba(139,92,246,0.25)`, background:'linear-gradient(135deg, rgba(139,92,246,0.1), rgba(6,182,212,0.05))', padding:'clamp(40px,6vw,72px) clamp(24px,5vw,60px)', textAlign:'center', position:'relative', overflow:'hidden', boxShadow:`0 0 100px rgba(139,92,246,0.12)` }}>
            <div style={{ position:'absolute', top:'50%', left:'50%', transform:'translate(-50%,-50%)', width:400, height:400, background:`radial-gradient(circle, rgba(139,92,246,0.1) 0%, transparent 65%)`, borderRadius:'50%', pointerEvents:'none' }}/>
            <div style={{ position:'relative' }}>
              <p style={{ fontSize:13, color:C.primary, fontWeight:700, letterSpacing:'0.12em', textTransform:'uppercase', marginBottom:14 }}>جاهز تبدأ؟</p>
              <h2 style={{ fontSize:'clamp(28px,4vw,52px)', fontWeight:900, letterSpacing:'-0.03em', marginBottom:16, lineHeight:1.1 }}>
                حوّل متجرك إلى
                <br />
                <span style={{ background:`linear-gradient(90deg, #a78bfa, #38bdf8, #34d399)`, WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>
                  آلة مبيعات ذكية
                </span>
              </h2>
              <p style={{ color:C.muted, fontSize:17, lineHeight:1.75, marginBottom:36, maxWidth:480, margin:'0 auto 36px' }}>
                انضم لمئات المتاجر وشاهد كيف يعمل البوت بينما أنت ترتاح.
              </p>
              <motion.button onClick={handleCTA} whileHover={{ scale:1.04 }} whileTap={{ scale:0.97 }}
                style={{ background:`linear-gradient(135deg,${C.primary},${C.secondary})`, borderRadius:16, padding:'16px 44px', fontSize:18, fontWeight:800, color:'#fff', border:'none', cursor:'pointer', boxShadow:`0 0 50px rgba(139,92,246,0.4)`, display:'inline-flex', alignItems:'center', gap:10 }}>
                <Icon d="M13 10V3L4 14h7v7l9-11h-7z" size={20} />
                ابدأ مجاناً الآن
              </motion.button>
              <p style={{ fontSize:12, color:C.muted, marginTop:16 }}>لا يلزم بطاقة ائتمانية · إعداد في أقل من دقيقتين</p>
            </div>
          </motion.div>
        </div>
      </Section>

      {/* ══════════════════════════════
          FOOTER
      ══════════════════════════════ */}
      <footer style={{ borderTop:`1px solid ${C.border}`, padding:'32px 24px' }}>
        <div className="max-w-6xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <div style={{ display:'flex', alignItems:'center', gap:10 }}>
            <div style={{ width:28, height:28, borderRadius:8, background:`linear-gradient(135deg,${C.primary},${C.secondary})`, display:'flex', alignItems:'center', justifyContent:'center' }}>
              <Icon d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" size={13} className="text-white" />
            </div>
            <span style={{ fontWeight:800, fontSize:15 }}>سلّابوت</span>
          </div>
          <p style={{ fontSize:12, color:'rgba(255,255,255,0.25)' }}>© ٢٠٢٥ سلّابوت — مساعد AI لمتاجر سلة. جميع الحقوق محفوظة.</p>
          <button onClick={handleCTA} style={{ fontSize:13, color:C.primary, fontWeight:600, background:'none', border:'none', cursor:'pointer' }} className="hover:text-white transition-colors">
            تسجيل الدخول ←
          </button>
        </div>
      </footer>

    </div>
  )
}
