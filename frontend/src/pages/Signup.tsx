import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Input, Button, Spinner } from '@heroui/react'
import { api, setToken, setStoreId, setIsSuper, setEmployee } from '../api'

function Icon({ paths, size = 16, className = '' }: {
  paths: string | string[]; size?: number; className?: string
}) {
  const arr = Array.isArray(paths) ? paths : [paths]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" className={className}>
      {arr.map((d, i) => <path key={i} d={d} />)}
    </svg>
  )
}

/* ── Channel / store logos for the (optional) integrations step ── */
function StoreLogo() {
  return (
    <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-teal-500 to-cyan-500 flex items-center justify-center flex-shrink-0">
      <Icon paths={['M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z', 'M3 6h18', 'M16 10a4 4 0 01-8 0']} size={20} className="text-white" />
    </div>
  )
}
function WhatsAppLogo() {
  return (
    <div className="w-11 h-11 rounded-2xl flex items-center justify-center flex-shrink-0" style={{ background: '#25D366' }}>
      <svg width={22} height={22} viewBox="0 0 24 24" fill="white" aria-hidden>
        <path d="M12 2a10 10 0 00-8.6 15.1L2 22l5-1.3A10 10 0 1012 2zm0 18.2a8.2 8.2 0 01-4.2-1.1l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1112 20.2zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8s-.4-.1-.6.1-.6.8-.8 1-.3.2-.6.1a6.7 6.7 0 01-2-1.2 7.4 7.4 0 01-1.3-1.7c-.1-.3 0-.4.1-.5l.4-.5.3-.4v-.4l-.8-1.8c-.2-.5-.4-.4-.5-.4h-.5a1 1 0 00-.8.3 3 3 0 00-.9 2.2 5.2 5.2 0 001.1 2.7 11.7 11.7 0 004.5 3.9c.6.3 1.1.4 1.5.5a3.6 3.6 0 001.7.1c.5-.1 1.5-.6 1.7-1.2s.2-1 .1-1.2z" />
      </svg>
    </div>
  )
}
function MetaLogo() {
  return (
    <div className="w-11 h-11 rounded-2xl flex items-center justify-center flex-shrink-0"
      style={{ background: 'linear-gradient(45deg,#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5)' }}>
      <Icon paths={['M7 2h10a5 5 0 015 5v10a5 5 0 01-5 5H7a5 5 0 01-5-5V7a5 5 0 015-5z', 'M12 8a4 4 0 100 8 4 4 0 000-8z', 'M17.5 6.5h.01']} size={20} className="text-white" />
    </div>
  )
}

/**
 * Self-service merchant signup.
 *
 * Two steps in one page:
 *   1. Account details  → creates the 7ayak account + logs the merchant in.
 *   2. Connect integrations (OPTIONAL) → cards for the store platform, WhatsApp,
 *      and Instagram/Messenger. "ربط الآن" routes to the existing, working
 *      connect UI (Integrations / Settings); the merchant can skip and link
 *      anytime later from the dashboard.
 */
export default function Signup() {
  const navigate = useNavigate()

  const [step, setStep]         = useState<'account' | 'integrations'>('account')
  const [newStoreId, setNewStoreId] = useState('')

  const [name, setName]         = useState('')
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm]   = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')

  const inputCls = {
    inputWrapper: 'border-slate-200 hover:border-teal-400 focus-within:!border-teal-500 bg-slate-50 hover:bg-white h-12 rounded-2xl transition-all',
    input: 'text-sm font-semibold text-slate-800 placeholder:text-slate-400',
  }

  async function handleSubmit() {
    if (loading) return
    setError('')
    if (!name.trim())            { setError('يرجى إدخال الاسم الكامل'); return }
    if (!email.trim())           { setError('يرجى إدخال البريد الإلكتروني'); return }
    if (password.length < 8)     { setError('كلمة المرور يجب أن تكون 8 أحرف على الأقل'); return }
    if (password !== confirm)    { setError('كلمتا المرور غير متطابقتين'); return }
    setLoading(true)
    try {
      const res = await api.signup(name.trim(), email.trim(), password)
      setToken(res.token)
      setStoreId(res.store_id)
      setIsSuper(res.is_super)
      setEmployee(res.employee)
      setNewStoreId(res.store_id)
      // Account created + logged in. Show the optional "connect integrations"
      // step instead of dropping straight into the dashboard.
      setStep('integrations')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'تعذّر إنشاء الحساب، حاول مرة أخرى')
    } finally {
      setLoading(false)
    }
  }

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSubmit()
  }

  // replace:true so a browser "back" doesn't return to the half-finished
  // signup flow (the account already exists at this point).
  const goDashboard = () => navigate(`/store/${newStoreId}`, { replace: true })
  const connect = (path: string) => navigate(path, { replace: true })

  const channels = [
    {
      id: 'store',
      logo: <StoreLogo />,
      title: 'متجرك الإلكتروني',
      desc: 'اربط سلّة أو زد أو شوبيفاي — نسحب منتجاتك وطلباتك تلقائياً.',
      go: `/store/${newStoreId}/integrations`,
    },
    {
      id: 'whatsapp',
      logo: <WhatsAppLogo />,
      title: 'واتساب',
      desc: 'اربط رقم واتساب الأعمال ليرد البوت على عملائك ٢٤/٧.',
      go: `/store/${newStoreId}/settings`,
    },
    {
      id: 'meta',
      logo: <MetaLogo />,
      title: 'انستقرام وماسنجر',
      desc: 'وحّد رسائل انستقرام وفيسبوك ماسنجر في نفس لوحة المحادثات.',
      go: `/store/${newStoreId}/settings`,
    },
  ]

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#f8f9fe] p-4 relative overflow-hidden" dir="rtl">

      {/* Background glows */}
      <div className="absolute top-[-10%] right-[-10%] w-[500px] h-[500px] bg-teal-400/20 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[-10%] left-[-10%] w-[500px] h-[500px] bg-cyan-400/15 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute inset-0 bg-[radial-gradient(#cbd5e0_1px,transparent_1px)] [background-size:24px_24px] opacity-30 pointer-events-none" />

      <div className="w-full max-w-md relative z-10 animate-in fade-in slide-in-from-bottom-6 duration-700">

        {/* Logo */}
        <div className="text-center mb-8 space-y-3">
          <img
            src="/logo.png"
            alt="حياك"
            style={{ maxWidth: '100%', height: 'auto', width: '180px' }}
            className="mx-auto"
          />
          <p className="text-sm text-slate-500 font-medium">المساعد الذكي لمتجرك</p>
        </div>

        {/* Card */}
        <div className="bg-white border border-slate-200 rounded-3xl shadow-soft-lg overflow-hidden">
          <div className="h-[3px] bg-gradient-to-r from-teal-400 to-cyan-500" />

          {/* ── Step 1: account details ── */}
          {step === 'account' && (
            <div className="p-6 sm:p-8 space-y-5">

              <div>
                <h2 className="text-xl font-black text-slate-800 mb-1">إنشاء حساب جديد</h2>
                <p className="text-xs text-slate-500">ابدأ مجاناً — اربط متجرك بعد إنشاء الحساب</p>
              </div>

              {/* Name */}
              <div>
                <label className="block text-sm font-semibold text-slate-600 mb-1.5">الاسم الكامل</label>
                <Input
                  placeholder="محمد عبدالله"
                  type="text"
                  value={name}
                  onValueChange={v => { setName(v); setError('') }}
                  variant="bordered"
                  autoComplete="name"
                  classNames={inputCls}
                  onKeyDown={handleKey}
                  startContent={
                    <Icon paths={['M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2', 'M12 7a4 4 0 100 8 4 4 0 000-8z']} size={16} className="text-slate-500 flex-shrink-0 ml-2" />
                  }
                />
              </div>

              {/* Email */}
              <div>
                <label className="block text-sm font-semibold text-slate-600 mb-1.5">البريد الإلكتروني</label>
                <Input
                  placeholder="you@example.com"
                  type="email"
                  value={email}
                  onValueChange={v => { setEmail(v); setError('') }}
                  variant="bordered"
                  autoComplete="email"
                  classNames={inputCls}
                  onKeyDown={handleKey}
                  startContent={
                    <Icon paths={['M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z', 'M22 6l-10 7L2 6']} size={16} className="text-slate-500 flex-shrink-0 ml-2" />
                  }
                />
              </div>

              {/* Password */}
              <div>
                <label className="block text-sm font-semibold text-slate-600 mb-1.5">كلمة المرور</label>
                <Input
                  placeholder="8 أحرف على الأقل"
                  type="password"
                  value={password}
                  onValueChange={v => { setPassword(v); setError('') }}
                  variant="bordered"
                  autoComplete="new-password"
                  classNames={inputCls}
                  onKeyDown={handleKey}
                  startContent={
                    <Icon paths={['M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z', 'M12 7V7a4 4 0 018 0v4H4V7a4 4 0 018 0z']} size={16} className="text-slate-500 flex-shrink-0 ml-2" />
                  }
                />
              </div>

              {/* Confirm password */}
              <div>
                <label className="block text-sm font-semibold text-slate-600 mb-1.5">تأكيد كلمة المرور</label>
                <Input
                  placeholder="أعد إدخال كلمة المرور"
                  type="password"
                  value={confirm}
                  onValueChange={v => { setConfirm(v); setError('') }}
                  variant="bordered"
                  autoComplete="new-password"
                  classNames={inputCls}
                  onKeyDown={handleKey}
                  startContent={
                    <Icon paths={['M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z', 'M12 7V7a4 4 0 018 0v4H4V7a4 4 0 018 0z']} size={16} className="text-slate-500 flex-shrink-0 ml-2" />
                  }
                />
              </div>

              {/* Error */}
              {error && (
                <div className="flex items-center gap-2.5 bg-red-50 border border-red-200 rounded-2xl px-4 py-3 text-xs font-bold text-red-600 animate-in fade-in duration-300">
                  <Icon paths="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" size={16} className="flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {/* Submit */}
              <Button
                className="w-full font-bold text-base h-12 text-white shadow-lg rounded-2xl hover:opacity-95 active:scale-[0.98] transition-all bg-gradient-to-r from-teal-500 to-cyan-500 shadow-teal-500/25"
                isLoading={loading}
                onPress={handleSubmit}
              >
                {loading ? <Spinner size="sm" /> : 'إنشاء الحساب'}
              </Button>

              <p className="text-[11px] text-slate-400 text-center mt-1">
                لديك حساب بالفعل؟
                {' '}
                <a href="/login" className="text-teal-600 font-bold hover:underline">تسجيل الدخول</a>
              </p>
            </div>
          )}

          {/* ── Step 2: connect integrations (optional) ── */}
          {step === 'integrations' && (
            <div className="p-6 sm:p-8 space-y-5">

              <div className="text-center space-y-1.5">
                <div className="w-12 h-12 mx-auto rounded-2xl bg-emerald-50 flex items-center justify-center">
                  <Icon paths="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" size={24} className="text-emerald-500" />
                </div>
                <h2 className="text-xl font-black text-slate-800">تم إنشاء حسابك 🎉</h2>
                <p className="text-xs text-slate-500">
                  اربط قنواتك ومتجرك الآن — أو تخطّاها واربطها لاحقاً من لوحة التحكم.
                  <span className="block mt-0.5 text-[11px] text-slate-400">خطوة اختيارية</span>
                </p>
              </div>

              {/* Integration cards */}
              <div className="space-y-2.5">
                {channels.map(ch => (
                  <div key={ch.id}
                    className="flex items-center gap-3 border border-slate-200 rounded-2xl p-3 hover:border-teal-300 transition-colors">
                    {ch.logo}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-bold text-slate-800">{ch.title}</p>
                      <p className="text-[11px] text-slate-500 leading-relaxed">{ch.desc}</p>
                    </div>
                    <button
                      onClick={() => connect(ch.go)}
                      className="flex-shrink-0 px-3.5 py-2 text-xs font-bold rounded-xl bg-teal-50 text-teal-700 hover:bg-teal-100 transition-colors flex items-center gap-1">
                      ربط الآن
                      <Icon paths="M15 19l-7-7 7-7" size={12} />
                    </button>
                  </div>
                ))}
              </div>

              {/* Skip / continue */}
              <Button
                className="w-full font-bold text-base h-12 text-white shadow-lg rounded-2xl hover:opacity-95 active:scale-[0.98] transition-all bg-gradient-to-r from-teal-500 to-cyan-500 shadow-teal-500/25"
                onPress={goDashboard}
              >
                تخطّي الآن — الذهاب للوحة التحكم
              </Button>

              <p className="text-[11px] text-slate-400 text-center">
                يمكنك ربط أي قناة في أي وقت من صفحة <span className="font-bold text-slate-500">التكاملات</span> و<span className="font-bold text-slate-500">الإعدادات</span>.
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="text-center mt-6">
          <p className="text-[11px] text-slate-400 font-medium">
            حياك — المساعد الذكي لمتجرك © {new Date().getFullYear()}
          </p>
        </div>
      </div>
    </div>
  )
}
