import { useEffect } from 'react'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
import { Button } from '@heroui/react'
import { getToken, getIsSuper, getStoreId } from '../api'

// ─────────────────────────── Per-code content table ─────────────────────────
//
// One source of truth for what each HTTP status looks like in the user-facing
// UI. Adding a new code = adding one row here; the rendering is data-driven.
//
// Tone goal: customer-readable Arabic, no jargon. Codes that mean "your
// fault" (400-class) explain what to do; codes that mean "our fault"
// (500-class) reassure + give a retry path.

type Tone = 'warning' | 'danger' | 'info' | 'auth'

interface ErrorMeta {
  title:       string
  subtitle:    string
  body:        string
  tone:        Tone
  // Which buttons to show. Order matters — primary first.
  actions:     Array<'back' | 'home' | 'login' | 'retry' | 'support'>
}

const META: Record<string, ErrorMeta> = {
  '400': {
    title:    'طلب غير صحيح',
    subtitle: 'البيانات المُرسلة غير مكتملة أو غير صحيحة',
    body:     'يبدو أن الطلب الذي أرسلته يحتوي على بيانات ناقصة أو غير صالحة. تأكد من تعبئة جميع الحقول المطلوبة وحاول مجدداً.',
    tone:     'warning',
    actions:  ['back', 'home'],
  },
  '401': {
    title:    'يجب تسجيل الدخول',
    subtitle: 'الجلسة منتهية أو غير صالحة',
    body:     'هذا القسم يتطلب تسجيل الدخول. سجّل دخولك مجدداً للمتابعة.',
    tone:     'auth',
    actions:  ['login', 'home'],
  },
  '402': {
    title:    'يتطلب الدفع',
    subtitle: 'الاشتراك غير نشط أو الحد المسموح به مكتمل',
    body:     'لا يمكن إكمال هذا الإجراء حالياً بسبب اشتراك غير نشط أو تجاوز الحد المسموح. تواصل مع فريق المبيعات لتفعيل الخدمة.',
    tone:     'warning',
    actions:  ['support', 'home'],
  },
  '403': {
    title:    'غير مصرح بالوصول',
    subtitle: 'صلاحياتك لا تسمح بفتح هذه الصفحة',
    body:     'هذا القسم متاح لمالك المتجر أو لصلاحيات معيّنة فقط. لو كنت تظن أن هذا خطأ، تواصل مع مالك المتجر.',
    tone:     'danger',
    actions:  ['back', 'home'],
  },
  '404': {
    title:    'الصفحة غير موجودة',
    subtitle: 'الرابط الذي حاولت فتحه غير متاح',
    body:     'إما أن الرابط مكتوب بشكل خاطئ، أو أن الصفحة تم نقلها أو حذفها. ارجع للصفحة الرئيسية لتكمل من هناك.',
    tone:     'info',
    actions:  ['back', 'home'],
  },
  '408': {
    title:    'انتهت مهلة الطلب',
    subtitle: 'الاتصال أبطأ من المتوقع',
    body:     'الخادم انتظر طويلاً ولم يستلم الطلب كاملاً. تأكد من اتصالك بالإنترنت وحاول مجدداً.',
    tone:     'warning',
    actions:  ['retry', 'home'],
  },
  '410': {
    title:    'الصفحة لم تعد متاحة',
    subtitle: 'تم إزالة هذا المورد بشكل دائم',
    body:     'هذا الرابط كان يعمل سابقاً لكن تمت إزالته نهائياً. ابحث عن البديل من القائمة الرئيسية.',
    tone:     'info',
    actions:  ['home'],
  },
  '413': {
    title:    'حجم البيانات كبير',
    subtitle: 'الملف أو الرسالة تجاوزت الحد المسموح',
    body:     'حاول رفع ملف أصغر أو تقصير الرسالة. الحد الأقصى يختلف حسب نوع الإجراء.',
    tone:     'warning',
    actions:  ['back', 'home'],
  },
  '422': {
    title:    'البيانات المرسلة غير صحيحة',
    subtitle: 'فشل التحقق من بعض الحقول',
    body:     'بعض الحقول لا تستوفي الشروط المطلوبة. راجع رسالة الخطأ التفصيلية وأعد المحاولة.',
    tone:     'warning',
    actions:  ['back', 'home'],
  },
  '429': {
    title:    'محاولات كثيرة في وقت قصير',
    subtitle: 'تم تطبيق حد مؤقت لحماية النظام',
    body:     'أرسلت عدداً كبيراً من الطلبات في فترة قصيرة. انتظر دقيقة أو دقيقتين ثم حاول مرة أخرى.',
    tone:     'warning',
    actions:  ['retry', 'home'],
  },
  '500': {
    title:    'خطأ غير متوقع في الخادم',
    subtitle: 'حصلت مشكلة من جهتنا — نعمل على إصلاحها',
    body:     'لم نتمكن من إكمال الطلب بسبب خطأ داخلي. حاول مرة أخرى بعد قليل؛ إن استمرت المشكلة، تواصل مع الدعم وأرسل لنا تفاصيل ما كنت تفعل.',
    tone:     'danger',
    actions:  ['retry', 'home', 'support'],
  },
  '502': {
    title:    'خطأ في البوابة',
    subtitle: 'الخادم الوسيط لم يتلقَ رداً صالحاً',
    body:     'الخدمة الخلفية لم تستجب بشكل صحيح. عادة هذه الحالة مؤقتة — حاول بعد لحظات.',
    tone:     'danger',
    actions:  ['retry', 'home'],
  },
  '503': {
    title:    'الخدمة غير متاحة مؤقتاً',
    subtitle: 'النظام تحت الصيانة أو مشغول',
    body:     'الخدمة في صيانة قصيرة أو يعمل النظام تحت ضغط عالي. حاول بعد قليل.',
    tone:     'warning',
    actions:  ['retry', 'home', 'support'],
  },
  '504': {
    title:    'انتهت مهلة الخادم',
    subtitle: 'الرد تأخر أكثر من المسموح',
    body:     'الخادم استغرق وقتاً طويلاً ولم يستكمل الطلب. حاول بعد قليل أو راجع اتصال الإنترنت.',
    tone:     'warning',
    actions:  ['retry', 'home'],
  },
}

// Fallback for anything we didn't explicitly model — still want a clean
// Arabic page rather than a raw browser error.
const FALLBACK: ErrorMeta = {
  title:    'حدث خطأ ما',
  subtitle: 'تعذّر إكمال العملية',
  body:     'وقع خطأ غير معروف. ارجع إلى الصفحة السابقة أو الرئيسية وحاول مرة أخرى.',
  tone:     'danger',
  actions:  ['back', 'home', 'support'],
}

// ─────────────────────────── Tone → colour palette ────────────────────────
const TONE_STYLES: Record<Tone, {
  badge: string
  ring:  string
  glow:  string
  iconColor: string
}> = {
  warning: {
    badge:     'bg-amber-50 text-amber-700 border-amber-200',
    ring:      'ring-amber-100',
    glow:      'from-amber-100/40 via-amber-50/0',
    iconColor: 'text-amber-500',
  },
  danger: {
    badge:     'bg-rose-50 text-rose-700 border-rose-200',
    ring:      'ring-rose-100',
    glow:      'from-rose-100/50 via-rose-50/0',
    iconColor: 'text-rose-500',
  },
  info: {
    badge:     'bg-sky-50 text-sky-700 border-sky-200',
    ring:      'ring-sky-100',
    glow:      'from-sky-100/40 via-sky-50/0',
    iconColor: 'text-sky-500',
  },
  auth: {
    badge:     'bg-indigo-50 text-indigo-700 border-indigo-200',
    ring:      'ring-indigo-100',
    glow:      'from-indigo-100/40 via-indigo-50/0',
    iconColor: 'text-indigo-500',
  },
}

// ─────────────────────────── Icon helper ──────────────────────────────────
function Icon({ paths, size = 28, className = '' }: {
  paths: string | string[]; size?: number; className?: string
}) {
  const arr = Array.isArray(paths) ? paths : [paths]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth={1.8}
         strokeLinecap="round" strokeLinejoin="round" className={className}>
      {arr.map((d, i) => <path key={i} d={d} />)}
    </svg>
  )
}

// One icon per tone — keeps the page recognizable without per-code icons.
const TONE_ICON: Record<Tone, string[]> = {
  warning: ['M12 9v4', 'M12 17h.01', 'M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z'],
  danger:  ['M12 9v4', 'M12 17h.01', 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z'],
  info:    ['M12 16v-4', 'M12 8h.01', 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z'],
  auth:    ['M16 11V7a4 4 0 1 0-8 0v4', 'M5 11h14v10H5z'],
}

// ─────────────────────────── Component ───────────────────────────────────
interface Props {
  // If provided, takes precedence over the URL :code segment. Lets pages
  // render an inline error (e.g. <ErrorPage code={500} />) instead of
  // routing the whole app to /error/500.
  code?:    number | string
  // Override the body text for the rare case where we have a more
  // specific message from the server (e.g. detail from a 403 JSON).
  message?: string
}

export default function ErrorPage({ code: codeProp, message }: Props) {
  const params   = useParams<{ code?: string }>()
  const location = useLocation()
  const navigate = useNavigate()

  const rawCode = String(codeProp ?? params.code ?? '404').trim()
  const meta    = META[rawCode] ?? FALLBACK
  const tone    = TONE_STYLES[meta.tone]

  // Helpful for ops — surfaces the failing path in the browser title so
  // bug reports include it without the user having to copy the URL.
  useEffect(() => {
    document.title = `${rawCode} — ${meta.title} | Hayyak`
    return () => { document.title = 'Hayyak' }
  }, [rawCode, meta.title])

  // ── Action handlers ────────────────────────────────────────────────────
  const goBack = () => {
    if (window.history.length > 1) navigate(-1)
    else goHome()
  }
  const goHome = () => {
    const token   = getToken()
    const isSuper = getIsSuper()
    if (!token) {
      navigate('/landing', { replace: true })
    } else if (isSuper) {
      navigate('/admin', { replace: true })
    } else {
      navigate(`/store/${getStoreId() || ''}`, { replace: true })
    }
  }
  const goLogin   = () => navigate('/login',  { replace: true })
  const retry     = () => window.location.reload()
  const support   = () => window.open('mailto:support@sallabot.app?subject=' + encodeURIComponent(`خطأ ${rawCode} على ${location.pathname}`))

  const ACTION_BUTTONS: Record<string, { label: string; onClick: () => void; primary?: boolean }> = {
    back:    { label: 'رجوع',                onClick: goBack  },
    home:    { label: 'الصفحة الرئيسية',     onClick: goHome,  primary: true },
    login:   { label: 'تسجيل الدخول',        onClick: goLogin, primary: true },
    retry:   { label: 'حاول مرة أخرى',       onClick: retry,   primary: true },
    support: { label: 'تواصل مع الدعم',      onClick: support },
  }

  // Primary = first; others = ghost. Filter then sort so primary stays first.
  const buttons = meta.actions
    .map((a) => ({ key: a, ...ACTION_BUTTONS[a] }))
    .filter(Boolean)

  return (
    <div dir="rtl" className="min-h-screen flex items-center justify-center bg-gradient-to-b from-slate-50 via-white to-slate-50 px-4 py-12">
      {/* Soft accent glow behind the card — picks up the tone colour */}
      <div className={`pointer-events-none absolute inset-x-0 top-0 h-72 bg-gradient-to-b ${tone.glow} to-transparent`} aria-hidden />

      <div className={`relative w-full max-w-xl rounded-3xl bg-white shadow-xl ring-1 ${tone.ring} border border-slate-100 p-10 md:p-12`}>
        {/* Icon badge */}
        <div className={`mx-auto w-16 h-16 rounded-2xl flex items-center justify-center border ${tone.badge}`}>
          <Icon paths={TONE_ICON[meta.tone]} size={30} className={tone.iconColor} />
        </div>

        {/* Big numeric code */}
        <div className="mt-6 text-center">
          <div className="font-mono text-7xl md:text-8xl font-extrabold tracking-tight bg-gradient-to-b from-slate-900 to-slate-500 bg-clip-text text-transparent select-none">
            {rawCode}
          </div>
          <h1 className="mt-3 text-2xl md:text-3xl font-extrabold text-slate-900">
            {meta.title}
          </h1>
          <p className="mt-2 text-sm md:text-base text-slate-500">
            {meta.subtitle}
          </p>
        </div>

        {/* Body copy */}
        <p className="mt-6 text-center text-slate-700 leading-relaxed text-[15px]">
          {message || meta.body}
        </p>

        {/* Actions */}
        <div className="mt-8 flex flex-wrap gap-3 justify-center">
          {buttons.map((b) => (
            <Button
              key={b.key}
              onPress={b.onClick}
              color={b.primary ? 'primary' : 'default'}
              variant={b.primary ? 'solid' : 'flat'}
              radius="lg"
              className="min-w-[140px]"
            >
              {b.label}
            </Button>
          ))}
        </div>

        {/* Footer — request id placeholder so support emails are actionable.
            We don't have a real correlation id yet (M15 — structured logging
            is on the roadmap), so we show timestamp + path as the best
            available diagnostic. */}
        <div className="mt-10 pt-6 border-t border-slate-100 text-center text-xs text-slate-400 font-mono">
          {location.pathname}{location.search}
          <br />
          {new Date().toISOString()}
        </div>
      </div>
    </div>
  )
}
