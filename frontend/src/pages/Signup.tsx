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
 * Self-service merchant signup. Creates a platform-independent 7ayak account
 * and logs the merchant straight in. They link Salla / Shopify / Zid afterwards
 * from the dashboard's Integrations page.
 */
export default function Signup() {
  const navigate = useNavigate()

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
      navigate(`/store/${res.store_id}`, { replace: true })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'تعذّر إنشاء الحساب، حاول مرة أخرى')
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
