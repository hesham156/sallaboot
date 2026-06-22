import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Input, Button, Spinner } from '@heroui/react'
import {
  api, setToken, setStoreId, setIsSuper, setEmployee,
  getDeviceToken, setDeviceToken, isOtpChallenge, SessionResponse,
} from '../api'

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

const inputCls = {
  inputWrapper: 'border-slate-200 hover:border-teal-400 focus-within:!border-teal-500 bg-slate-50 hover:bg-white h-12 rounded-2xl transition-all',
  input: 'text-sm font-semibold text-slate-800 placeholder:text-slate-400',
}

/**
 * Single email/password login. /auth/login resolves the account kind
 * (super / employee / owner). When email 2FA is enabled and this device isn't
 * trusted, the response is {otp_required, challenge} and we show an OTP step;
 * a verified login stores a 30-day device-trust token to skip OTP next time.
 */
export default function Login() {
  const navigate = useNavigate()

  const [step, setStep]         = useState<'credentials' | 'otp' | 'forgot' | 'sent'>('credentials')
  const [email, setEmail]       = useState('')  // holds email OR store_id
  const [password, setPassword] = useState('')
  const [challenge, setChallenge] = useState('')
  const [code, setCode]         = useState('')
  const [forgotEmail, setForgotEmail] = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')

  function finalizeSession(res: SessionResponse) {
    if (res.device_token) setDeviceToken(email.trim(), res.device_token)
    setToken(res.token)
    setStoreId(res.store_id)
    setIsSuper(res.is_super)
    setEmployee(res.employee)
    navigate(res.is_super ? '/admin' : `/store/${res.store_id}`, { replace: true })
  }

  async function handleSubmit() {
    if (loading) return
    setError('')
    if (!email.trim())  { setError('يرجى إدخال البريد الإلكتروني أو معرّف المتجر'); return }
    if (!password)      { setError('يرجى إدخال كلمة المرور');       return }
    setLoading(true)
    try {
      const res = await api.login(email.trim(), password, getDeviceToken(email.trim()))
      if (isOtpChallenge(res)) {
        setChallenge(res.challenge)
        setCode('')
        setStep('otp')
      } else {
        finalizeSession(res)
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'البريد الإلكتروني أو كلمة المرور غير صحيحة')
    } finally {
      setLoading(false)
    }
  }

  async function handleVerify() {
    if (loading) return
    setError('')
    if (code.trim().length < 6) { setError('أدخل الرمز المكوّن من ٦ أرقام'); return }
    setLoading(true)
    try {
      const res = await api.otpVerify({
        email: email.trim(), password, code: code.trim(),
        challenge, purpose: 'login', remember_device: true,
      })
      finalizeSession(res)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'رمز التحقق غير صحيح أو منتهي')
    } finally {
      setLoading(false)
    }
  }

  async function handleResend() {
    setError(''); setLoading(true)
    try {
      const res = await api.login(email.trim(), password, '')
      if (isOtpChallenge(res)) { setChallenge(res.challenge); setCode('') }
      else finalizeSession(res)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'تعذّر إعادة إرسال الرمز')
    } finally { setLoading(false) }
  }

  async function handleForgot() {
    if (loading) return
    setError('')
    const addr = forgotEmail.trim() || email.trim()
    if (!addr) { setError('يرجى إدخال البريد الإلكتروني أو معرّف المتجر'); return }
    setLoading(true)
    try {
      await api.forgotPassword(addr)
      setStep('sent')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'تعذّر إرسال الرسالة، حاول مجدداً')
    } finally { setLoading(false) }
  }

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      if (step === 'otp') handleVerify()
      else if (step === 'forgot') handleForgot()
      else handleSubmit()
    }
  }

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
          <p className="text-sm text-slate-500 font-medium">المساعد الذكي لمتاجر سلة</p>
        </div>

        {/* Card */}
        <div className="bg-white border border-slate-200 rounded-3xl shadow-soft-lg overflow-hidden">
          <div className="h-[3px] bg-gradient-to-r from-teal-400 to-cyan-500" />

          {/* ── Step: credentials ── */}
          {step === 'credentials' && (
            <div className="p-6 sm:p-8 space-y-5">

              <div>
                <h2 className="text-xl font-black text-slate-800 mb-1">تسجيل الدخول</h2>
                <p className="text-xs text-slate-500">أدخل بياناتك للوصول إلى لوحتك</p>
              </div>

              {/* Email */}
              <div>
                <label className="block text-sm font-semibold text-slate-600 mb-1.5">البريد الإلكتروني أو معرّف المتجر</label>
                <Input
                  placeholder="you@example.com أو store_id"
                  type="text"
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
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-sm font-semibold text-slate-600">كلمة المرور</label>
                  <button
                    type="button"
                    onClick={() => { setForgotEmail(email.trim()); setError(''); setStep('forgot') }}
                    className="text-[11px] text-teal-600 font-bold hover:underline"
                  >
                    نسيت كلمة المرور؟
                  </button>
                </div>
                <Input
                  placeholder="أدخل كلمة المرور"
                  type="password"
                  value={password}
                  onValueChange={v => { setPassword(v); setError('') }}
                  variant="bordered"
                  autoComplete="current-password"
                  classNames={inputCls}
                  onKeyDown={handleKey}
                  startContent={
                    <Icon paths={['M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z', 'M12 7V7a4 4 0 018 0v4H4V7a4 4 0 018 0z']} size={16} className="text-slate-500 flex-shrink-0 ml-2" />
                  }
                />
              </div>

              {error && (
                <div className="flex items-center gap-2.5 bg-red-50 border border-red-200 rounded-2xl px-4 py-3 text-xs font-bold text-red-600 animate-in fade-in duration-300">
                  <Icon paths="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" size={16} className="flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <Button
                className="w-full font-bold text-base h-12 text-white shadow-lg rounded-2xl hover:opacity-95 active:scale-[0.98] transition-all bg-gradient-to-r from-teal-500 to-cyan-500 shadow-teal-500/25"
                isLoading={loading}
                onPress={handleSubmit}
              >
                {loading ? <Spinner size="sm" /> : 'دخول'}
              </Button>

              <p className="text-[11px] text-slate-400 text-center mt-1">
                ليس لديك حساب؟
                {' '}
                <a href="/signup" className="text-teal-600 font-bold hover:underline">إنشاء حساب جديد</a>
              </p>
            </div>
          )}

          {/* ── Step: forgot password ── */}
          {step === 'forgot' && (
            <div className="p-6 sm:p-8 space-y-5">
              <div className="text-center space-y-1.5">
                <div className="w-12 h-12 mx-auto rounded-2xl bg-teal-50 flex items-center justify-center">
                  <Icon paths={['M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z']} size={22} className="text-teal-500" />
                </div>
                <h2 className="text-xl font-black text-slate-800">نسيت كلمة المرور؟</h2>
                <p className="text-xs text-slate-500">أدخل بريدك الإلكتروني وسنرسل لك رابط إعادة التعيين</p>
              </div>

              <div>
                <label className="block text-sm font-semibold text-slate-600 mb-1.5">البريد الإلكتروني أو معرّف المتجر</label>
                <Input
                  placeholder="you@example.com أو store_id"
                  type="text"
                  value={forgotEmail}
                  onValueChange={v => { setForgotEmail(v); setError('') }}
                  variant="bordered"
                  autoFocus
                  autoComplete="email"
                  classNames={inputCls}
                  onKeyDown={handleKey}
                  startContent={
                    <Icon paths={['M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z', 'M22 6l-10 7L2 6']} size={16} className="text-slate-500 flex-shrink-0 ml-2" />
                  }
                />
              </div>

              {error && (
                <div className="flex items-center gap-2.5 bg-red-50 border border-red-200 rounded-2xl px-4 py-3 text-xs font-bold text-red-600 animate-in fade-in duration-300">
                  <Icon paths="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" size={16} className="flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <Button
                className="w-full font-bold text-base h-12 text-white shadow-lg rounded-2xl hover:opacity-95 active:scale-[0.98] transition-all bg-gradient-to-r from-teal-500 to-cyan-500 shadow-teal-500/25"
                isLoading={loading}
                onPress={handleForgot}
              >
                {loading ? <Spinner size="sm" /> : 'إرسال رابط إعادة التعيين'}
              </Button>

              <button onClick={() => { setStep('credentials'); setError('') }}
                className="w-full text-[11px] text-slate-400 font-bold hover:text-slate-600">
                → رجوع لتسجيل الدخول
              </button>
            </div>
          )}

          {/* ── Step: reset link sent ── */}
          {step === 'sent' && (
            <div className="p-6 sm:p-8 space-y-5 text-center">
              <div className="w-14 h-14 mx-auto rounded-2xl bg-teal-50 flex items-center justify-center">
                <Icon paths={['M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z']} size={28} className="text-teal-500" />
              </div>
              <div className="space-y-1">
                <h2 className="text-xl font-black text-slate-800">تم إرسال الرابط!</h2>
                <p className="text-xs text-slate-500 leading-relaxed">
                  إذا كان البريد الإلكتروني مسجّلاً لدينا، ستصلك رسالة بها رابط إعادة تعيين كلمة المرور.
                  <br />تحقق من صندوق البريد الوارد أو مجلد الـ Spam.
                </p>
              </div>
              <button onClick={() => { setStep('credentials'); setError('') }}
                className="text-sm text-teal-600 font-bold hover:underline">
                → رجوع لتسجيل الدخول
              </button>
            </div>
          )}

          {/* ── Step: OTP ── */}
          {step === 'otp' && (
            <div className="p-6 sm:p-8 space-y-5">

              <div className="text-center space-y-1.5">
                <div className="w-12 h-12 mx-auto rounded-2xl bg-teal-50 flex items-center justify-center">
                  <Icon paths={['M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z', 'M22 6l-10 7L2 6']} size={22} className="text-teal-500" />
                </div>
                <h2 className="text-xl font-black text-slate-800">رمز التحقق</h2>
                <p className="text-xs text-slate-500">
                  أرسلنا رمزاً من ٦ أرقام إلى بريدك الإلكتروني. أدخله للمتابعة.
                </p>
              </div>

              <Input
                placeholder="——————"
                inputMode="numeric"
                value={code}
                onValueChange={v => { setCode(v.replace(/\D/g, '').slice(0, 6)); setError('') }}
                variant="bordered"
                autoFocus
                classNames={{
                  inputWrapper: 'border-slate-200 hover:border-teal-400 focus-within:!border-teal-500 bg-slate-50 hover:bg-white h-14 rounded-2xl transition-all',
                  input: 'text-center text-2xl font-black tracking-[0.4em] text-slate-800 placeholder:text-slate-300',
                }}
                onKeyDown={handleKey}
              />

              {error && (
                <div className="flex items-center gap-2.5 bg-red-50 border border-red-200 rounded-2xl px-4 py-3 text-xs font-bold text-red-600 animate-in fade-in duration-300">
                  <Icon paths="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" size={16} className="flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <Button
                className="w-full font-bold text-base h-12 text-white shadow-lg rounded-2xl hover:opacity-95 active:scale-[0.98] transition-all bg-gradient-to-r from-teal-500 to-cyan-500 shadow-teal-500/25"
                isLoading={loading}
                onPress={handleVerify}
              >
                {loading ? <Spinner size="sm" /> : 'تأكيد ودخول'}
              </Button>

              <div className="flex items-center justify-between text-[11px]">
                <button onClick={() => { setStep('credentials'); setError(''); setCode('') }}
                  className="text-slate-400 font-bold hover:text-slate-600">→ رجوع</button>
                <button onClick={handleResend} disabled={loading}
                  className="text-teal-600 font-bold hover:underline disabled:opacity-50">إعادة إرسال الرمز</button>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="text-center mt-6">
          <p className="text-[11px] text-slate-400 font-medium">
            حياك — المساعد الذكي لمتاجر سلة © {new Date().getFullYear()}
          </p>
        </div>
      </div>
    </div>
  )
}
