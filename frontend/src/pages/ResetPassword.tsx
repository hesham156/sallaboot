import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Input, Button, Spinner } from '@heroui/react'
import { api } from '../api'

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

export default function ResetPassword() {
  const navigate         = useNavigate()
  const [params]         = useSearchParams()
  const token            = params.get('token') || ''

  const [password, setPassword]   = useState('')
  const [confirm, setConfirm]     = useState('')
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState('')
  const [done, setDone]           = useState(false)

  async function handleReset() {
    if (loading) return
    setError('')
    if (!token) { setError('رابط إعادة التعيين غير صالح'); return }
    if (password.length < 8) { setError('كلمة المرور يجب أن تكون 8 أحرف على الأقل'); return }
    if (password !== confirm) { setError('كلمتا المرور غير متطابقتين'); return }
    setLoading(true)
    try {
      await api.resetPasswordWithToken(token, password)
      setDone(true)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'تعذّر إعادة التعيين. الرابط منتهي أو غير صالح.')
    } finally { setLoading(false) }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#f8f9fe] p-4 relative overflow-hidden" dir="rtl">

      <div className="absolute top-[-10%] right-[-10%] w-[500px] h-[500px] bg-teal-400/20 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[-10%] left-[-10%] w-[500px] h-[500px] bg-cyan-400/15 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute inset-0 bg-[radial-gradient(#cbd5e0_1px,transparent_1px)] [background-size:24px_24px] opacity-30 pointer-events-none" />

      <div className="w-full max-w-md relative z-10 animate-in fade-in slide-in-from-bottom-6 duration-700">

        {/* Logo */}
        <div className="text-center mb-8 space-y-3">
          <img src="/logo.png" alt="حياك" style={{ maxWidth: '100%', height: 'auto', width: '180px' }} className="mx-auto" />
          <p className="text-sm text-slate-500 font-medium">المساعد الذكي لمتاجر سلة</p>
        </div>

        <div className="bg-white border border-slate-200 rounded-3xl shadow-soft-lg overflow-hidden">
          <div className="h-[3px] bg-gradient-to-r from-teal-400 to-cyan-500" />

          {done ? (
            <div className="p-6 sm:p-8 space-y-5 text-center">
              <div className="w-14 h-14 mx-auto rounded-2xl bg-teal-50 flex items-center justify-center">
                <Icon paths="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" size={28} className="text-teal-500" />
              </div>
              <div className="space-y-1">
                <h2 className="text-xl font-black text-slate-800">تم تحديث كلمة المرور!</h2>
                <p className="text-xs text-slate-500">يمكنك الآن تسجيل الدخول بكلمة المرور الجديدة.</p>
              </div>
              <Button
                className="w-full font-bold text-base h-12 text-white shadow-lg rounded-2xl bg-gradient-to-r from-teal-500 to-cyan-500"
                onPress={() => navigate('/login', { replace: true })}
              >
                تسجيل الدخول
              </Button>
            </div>
          ) : (
            <div className="p-6 sm:p-8 space-y-5">
              <div>
                <h2 className="text-xl font-black text-slate-800 mb-1">إعادة تعيين كلمة المرور</h2>
                <p className="text-xs text-slate-500">أدخل كلمة مرور جديدة لحسابك</p>
              </div>

              {!token && (
                <div className="flex items-center gap-2.5 bg-red-50 border border-red-200 rounded-2xl px-4 py-3 text-xs font-bold text-red-600">
                  <Icon paths="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" size={16} className="flex-shrink-0" />
                  <span>رابط إعادة التعيين غير صالح. يرجى طلب رابط جديد.</span>
                </div>
              )}

              <div>
                <label className="block text-sm font-semibold text-slate-600 mb-1.5">كلمة المرور الجديدة</label>
                <Input
                  placeholder="8 أحرف على الأقل"
                  type="password"
                  value={password}
                  onValueChange={v => { setPassword(v); setError('') }}
                  variant="bordered"
                  autoFocus
                  autoComplete="new-password"
                  classNames={inputCls}
                  onKeyDown={e => e.key === 'Enter' && handleReset()}
                  startContent={
                    <Icon paths={['M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z', 'M12 7V7a4 4 0 018 0v4H4V7a4 4 0 018 0z']} size={16} className="text-slate-500 flex-shrink-0 ml-2" />
                  }
                />
              </div>

              <div>
                <label className="block text-sm font-semibold text-slate-600 mb-1.5">تأكيد كلمة المرور</label>
                <Input
                  placeholder="أعد كتابة كلمة المرور"
                  type="password"
                  value={confirm}
                  onValueChange={v => { setConfirm(v); setError('') }}
                  variant="bordered"
                  autoComplete="new-password"
                  classNames={inputCls}
                  onKeyDown={e => e.key === 'Enter' && handleReset()}
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
                isDisabled={!token}
                onPress={handleReset}
              >
                {loading ? <Spinner size="sm" /> : 'حفظ كلمة المرور الجديدة'}
              </Button>

              <p className="text-[11px] text-slate-400 text-center">
                <a href="/login" className="text-teal-600 font-bold hover:underline">→ رجوع لتسجيل الدخول</a>
              </p>
            </div>
          )}
        </div>

        <div className="text-center mt-6">
          <p className="text-[11px] text-slate-400 font-medium">
            حياك — المساعد الذكي لمتاجر سلة © {new Date().getFullYear()}
          </p>
        </div>
      </div>
    </div>
  )
}
