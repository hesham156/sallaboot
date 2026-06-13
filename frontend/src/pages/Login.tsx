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

/**
 * Single email/password login. The backend's /auth/login figures out
 * whether this email belongs to a super admin, a store employee, or a
 * store owner — we just submit credentials and route based on the
 * `is_super` flag in the response.
 */
export default function Login() {
  const navigate = useNavigate()

  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')

  async function handleSubmit() {
    if (loading) return
    setError('')
    if (!email.trim())  { setError('يرجى إدخال البريد الإلكتروني'); return }
    if (!password)      { setError('يرجى إدخال كلمة المرور');       return }
    setLoading(true)
    try {
      const res = await api.login(email.trim(), password)
      setToken(res.token)
      setStoreId(res.store_id)
      setIsSuper(res.is_super)
      setEmployee(res.employee)
      navigate(res.is_super ? '/admin' : `/store/${res.store_id}`, { replace: true })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'البريد الإلكتروني أو كلمة المرور غير صحيحة')
    } finally {
      setLoading(false)
    }
  }

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSubmit()
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#f8f9fe] p-4 relative overflow-hidden" dir="rtl">

      {/* Background glows */}
      <div className="absolute top-[-10%] right-[-10%] w-[500px] h-[500px] bg-teal-400/20 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[-10%] left-[-10%] w-[500px] h-[500px] bg-cyan-400/15 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute inset-0 bg-[radial-gradient(#cbd5e0_1px,transparent_1px)] [background-size:24px_24px] opacity-30 pointer-events-none" />

      <div className="w-full max-w-md relative z-10 animate-in fade-in slide-in-from-bottom-6 duration-700">

        {/* Logo */}
        <div className="text-center mb-8 space-y-4">
          <div className="w-20 h-20 mx-auto rounded-3xl bg-gradient-to-br from-teal-400 to-cyan-500 flex items-center justify-center shadow-xl shadow-teal-500/25 hover:scale-105 transition-transform duration-300">
            <Icon paths="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" size={32} className="text-white" />
          </div>
          <div>
            <h1 className="text-3xl font-black tracking-tight text-slate-800">
              سـلّابـوت
            </h1>
            <p className="text-sm text-slate-500 font-medium mt-1">المساعد الذكي لمتاجر سلة</p>
          </div>
        </div>

        {/* Card */}
        <div className="bg-white border border-slate-200 rounded-3xl shadow-soft-lg overflow-hidden">
          <div className="h-[3px] bg-gradient-to-r from-teal-400 to-cyan-500" />

          <div className="p-6 sm:p-8 space-y-5">

            <div>
              <h2 className="text-xl font-black text-slate-800 mb-1">تسجيل الدخول</h2>
              <p className="text-xs text-slate-500">أدخل بياناتك للوصول إلى لوحتك</p>
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
                classNames={{
                  inputWrapper: 'border-slate-200 hover:border-teal-400 focus-within:!border-teal-500 bg-slate-50 hover:bg-white h-12 rounded-2xl transition-all',
                  input: 'text-sm font-semibold text-slate-800 placeholder:text-slate-400',
                }}
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
                placeholder="أدخل كلمة المرور"
                type="password"
                value={password}
                onValueChange={v => { setPassword(v); setError('') }}
                variant="bordered"
                autoComplete="current-password"
                classNames={{
                  inputWrapper: 'border-slate-200 hover:border-teal-400 focus-within:!border-teal-500 bg-slate-50 hover:bg-white h-12 rounded-2xl transition-all',
                  input: 'text-sm font-semibold text-slate-800 placeholder:text-slate-400',
                }}
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
              {loading ? <Spinner size="sm" /> : 'دخول'}
            </Button>

            <p className="text-[11px] text-slate-400 text-center mt-1">
              لو متجرك مش متربط بعد،
              {' '}
              <a href="/auth/salla" className="text-teal-600 font-bold hover:underline">ربط المتجر بـ Salla</a>
            </p>
          </div>
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
