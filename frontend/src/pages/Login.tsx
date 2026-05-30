import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
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
  const { storeId } = useParams<{ storeId?: string }>()
  const navigate    = useNavigate()

  const [mode, setMode]           = useState<'super' | 'store'>(storeId ? 'store' : 'super')
  const [inputStoreId, setInputStoreId] = useState(storeId || '')
  const [password, setPassword]   = useState('')
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState('')

  async function handleLogin() {
    setError(''); setLoading(true)
    try {
      if (mode === 'super') {
        const res = await api.superLogin(password)
        setToken(res.token); setStoreId('super'); setIsSuper(true)
        navigate('/', { replace: true })
      } else {
        if (!inputStoreId.trim()) { setError('أدخل رقم المتجر'); return }
        const res = await api.storeLogin(inputStoreId.trim(), password)
        setToken(res.token); setStoreId(res.store_id); setIsSuper(false)
        navigate(`/store/${res.store_id}`, { replace: true })
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'خطأ في تسجيل الدخول')
    } finally { setLoading(false) }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4 relative overflow-hidden" dir="rtl">

      {/* Background glows */}
      <div className="absolute top-1/4 right-1/4 w-96 h-96 bg-blue-600/5 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-1/4 left-1/4 w-96 h-96 bg-indigo-600/5 rounded-full blur-3xl pointer-events-none" />

      <div className="w-full max-w-sm relative">

        {/* ── Logo ── */}
        <div className="text-center mb-8">
          <div className="w-16 h-16 mx-auto rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-2xl shadow-blue-500/30 mb-4">
            <Icon
              paths="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"
              size={28}
              className="text-white"
            />
          </div>
          <h1 className="text-2xl font-black text-white">بوت المتجر</h1>
          <p className="text-sm text-slate-500 mt-1">لوحة تحكم المساعد الذكي</p>
        </div>

        {/* ── Card ── */}
        <div className="bg-[#0c1627] border border-[#1c2d42] rounded-2xl overflow-hidden shadow-2xl">

          {/* Mode toggle */}
          <div className="flex border-b border-[#1c2d42]">
            {[
              { key: 'super', label: 'مدير عام', icon: 'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z' },
              { key: 'store', label: 'متجر', icon: ['M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z', 'M9 22V12h6v10'] },
            ].map(m => (
              <button
                key={m.key}
                onClick={() => { setMode(m.key as typeof mode); setError('') }}
                className={`flex-1 flex items-center justify-center gap-2 py-3.5 text-sm font-semibold transition-colors ${
                  mode === m.key
                    ? 'bg-blue-500/10 text-blue-400 border-b-2 border-b-blue-500'
                    : 'text-slate-500 hover:text-slate-300 hover:bg-[#111e32]'
                }`}
              >
                <Icon paths={m.icon} size={15} />
                {m.label}
              </button>
            ))}
          </div>

          {/* Form */}
          <div className="p-6 space-y-4">
            {mode === 'store' && (
              <Input
                label="رقم المتجر"
                placeholder="أدخل معرف المتجر"
                value={inputStoreId}
                onValueChange={setInputStoreId}
                variant="bordered"
                classNames={{
                  label: 'text-slate-400 text-sm',
                  inputWrapper: 'border-[#1c2d42] hover:border-slate-500 bg-[#111e32]',
                }}
                startContent={
                  <Icon paths={['M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z', 'M9 22V12h6v10']} size={15} className="text-slate-500 flex-shrink-0" />
                }
              />
            )}

            <Input
              label="كلمة المرور"
              placeholder={mode === 'super' ? 'كلمة مرور المدير العام' : 'كلمة مرور المتجر'}
              type="password"
              value={password}
              onValueChange={setPassword}
              variant="bordered"
              classNames={{
                label: 'text-slate-400 text-sm',
                inputWrapper: 'border-[#1c2d42] hover:border-slate-500 bg-[#111e32]',
              }}
              onKeyDown={e => e.key === 'Enter' && handleLogin()}
              startContent={
                <Icon paths={['M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z', 'M12 7V7a4 4 0 018 0v4H4V7a4 4 0 018 0z']} size={15} className="text-slate-500 flex-shrink-0" />
              }
            />

            {error && (
              <div className="flex items-center gap-2 bg-red-500/10 border border-red-500/20 rounded-xl px-3 py-2.5 text-sm text-red-400">
                <Icon paths="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" size={15} className="flex-shrink-0" />
                {error}
              </div>
            )}

            <Button
              color="primary"
              className="w-full font-bold text-base h-12 bg-gradient-to-r from-blue-600 to-indigo-600 shadow-lg shadow-blue-500/20"
              isLoading={loading}
              onPress={handleLogin}
            >
              {loading ? '' : 'دخول'}
            </Button>

            {mode === 'store' && (
              <p className="text-center text-xs text-slate-600">
                كلمة المرور الافتراضية هي رقم المتجر
              </p>
            )}
          </div>
        </div>

        {/* Footer */}
        <p className="text-center text-xs text-slate-700 mt-6">
          بوت المتجر — مساعد Salla الذكي
        </p>
      </div>
    </div>
  )
}
