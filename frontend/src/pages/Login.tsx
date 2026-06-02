import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Input, Button, Spinner } from '@heroui/react'
import { api, setToken, setStoreId, setIsSuper } from '../api'

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

export default function Login() {
  const navigate = useNavigate()

  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')

  async function handleLogin() {
    if (loading) return
    setError('')
    if (!email.trim())    { setError('يرجى إدخال البريد الإلكتروني'); return }
    if (!password)        { setError('يرجى إدخال كلمة المرور'); return }
    setLoading(true)
    try {
      const res = await api.superLogin(email.trim(), password)
      setToken(res.token); setStoreId('super'); setIsSuper(true)
      navigate('/', { replace: true })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'البريد الإلكتروني أو كلمة المرور غير صحيحة')
    } finally { setLoading(false) }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#f8f9fe] p-4 relative overflow-hidden" dir="rtl">

      {/* Soft background gradients (Purity teal/cyan) */}
      <div className="absolute top-[-10%] right-[-10%] w-[500px] h-[500px] bg-teal-400/20 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[-10%] left-[-10%] w-[500px] h-[500px] bg-cyan-400/15 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[350px] h-[350px] bg-teal-300/10 rounded-full blur-[100px] pointer-events-none" />

      {/* Subtle dot grid */}
      <div className="absolute inset-0 bg-[radial-gradient(#cbd5e0_1px,transparent_1px)] [background-size:24px_24px] opacity-30 pointer-events-none" />

      <div className="w-full max-w-md relative z-10 animate-in fade-in slide-in-from-bottom-6 duration-700">

        {/* ── Logo & Title ── */}
        <div className="text-center mb-8 space-y-4">
          <div className="relative group w-20 h-20 mx-auto rounded-3xl bg-gradient-to-br from-teal-400 to-cyan-500 flex items-center justify-center shadow-xl shadow-teal-500/25 hover:scale-105 transition-transform duration-300">
            <Icon
              paths="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"
              size={32}
              className="text-white"
            />
          </div>
          <div>
            <h1 className="text-3xl font-black tracking-tight text-slate-800">
              بـوت الـمـتـجـر <span className="text-gradient">SallaBot</span>
            </h1>
            <p className="text-sm text-slate-500 font-medium mt-2">لوحة تحكم المشرف — تسجيل دخول آمن</p>
          </div>
        </div>

        {/* ── Login Card ── */}
        <div className="bg-white border border-slate-200 rounded-3xl shadow-soft-lg p-6 sm:p-8 space-y-6 relative overflow-hidden">
          <div className="absolute top-0 inset-x-0 h-[3px] bg-gradient-to-r from-teal-400 to-cyan-500" />

          {/* Header badge */}
          <div className="flex items-center justify-center gap-2.5 py-3 rounded-2xl bg-teal-50 border border-teal-100">
            <Icon
              paths="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
              size={16}
              className="text-teal-600"
            />
            <span className="text-sm font-bold text-slate-700">دخول المشرف العام 🛡️</span>
          </div>

          {/* Form Content */}
          <div className="space-y-5">
            <Input
              label="البريد الإلكتروني"
              placeholder="admin@example.com"
              type="email"
              value={email}
              onValueChange={setEmail}
              variant="bordered"
              autoComplete="email"
              classNames={{
                label: 'text-slate-600 text-sm font-semibold mb-1',
                inputWrapper: 'border-slate-200 hover:border-teal-400 focus-within:!border-teal-500 bg-slate-50 hover:bg-white h-12 rounded-2xl transition-all duration-300',
                input: 'text-sm font-semibold text-slate-800 placeholder:text-slate-400',
              }}
              onKeyDown={e => e.key === 'Enter' && handleLogin()}
              startContent={
                <Icon paths={['M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z', 'M22 6l-10 7L2 6']} size={16} className="text-slate-500 flex-shrink-0 ml-2" />
              }
            />

            <Input
              label="كلمة المرور"
              placeholder="أدخل كلمة المرور"
              type="password"
              value={password}
              onValueChange={setPassword}
              variant="bordered"
              autoComplete="current-password"
              classNames={{
                label: 'text-slate-600 text-sm font-semibold mb-1',
                inputWrapper: 'border-slate-200 hover:border-teal-400 focus-within:!border-teal-500 bg-slate-50 hover:bg-white h-12 rounded-2xl transition-all duration-300',
                input: 'text-sm font-semibold text-slate-800 placeholder:text-slate-400',
              }}
              onKeyDown={e => e.key === 'Enter' && handleLogin()}
              startContent={
                <Icon paths={['M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z', 'M12 7V7a4 4 0 018 0v4H4V7a4 4 0 018 0z']} size={16} className="text-slate-500 flex-shrink-0 ml-2" />
              }
            />

            {error && (
              <div className="flex items-center gap-2.5 bg-red-50 border border-red-200 rounded-2xl px-4 py-3 text-xs font-bold text-red-600 animate-in fade-in duration-300">
                <Icon paths="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" size={16} className="flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <Button
              color="primary"
              className="w-full font-bold text-base h-12 bg-gradient-to-r from-teal-500 to-cyan-500 text-white shadow-lg shadow-teal-500/25 rounded-2xl hover:opacity-95 active:scale-[0.98] transition-all"
              isLoading={loading}
              onPress={handleLogin}
            >
              {loading ? <Spinner size="sm" color="white" /> : 'تسجيل الدخول الآمن'}
            </Button>
          </div>
        </div>

        {/* ── Footer ── */}
        <div className="text-center mt-6 space-y-1">
          <p className="text-[11px] text-slate-500 font-bold">
            بوت المتجر — المساعد الذكي المتكامل لمنصات سلة © {new Date().getFullYear()}
          </p>
          <p className="text-[10px] text-slate-400 font-medium">سحابي، مؤمن ومحمي بالكامل 🔒</p>
        </div>
      </div>
    </div>
  )
}
