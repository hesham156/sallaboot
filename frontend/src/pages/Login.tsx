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

type Tab = 'store' | 'admin'

export default function Login() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('store')

  // Store login fields
  const [storeId, setStoreIdInput] = useState('')
  const [storePass, setStorePass]  = useState('')

  // Admin login fields
  const [email, setEmail]       = useState('')
  const [adminPass, setAdminPass] = useState('')

  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState('')

  async function handleStoreLogin() {
    if (loading) return
    setError('')
    if (!storeId.trim()) { setError('يرجى إدخال معرّف المتجر'); return }
    if (!storePass)      { setError('يرجى إدخال كلمة المرور'); return }
    setLoading(true)
    try {
      const res = await api.storeLogin(storeId.trim(), storePass)
      setToken(res.token)
      setStoreId(res.store_id)
      setIsSuper(false)
      navigate(`/store/${res.store_id}`, { replace: true })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'معرّف المتجر أو كلمة المرور غير صحيحة')
    } finally { setLoading(false) }
  }

  async function handleAdminLogin() {
    if (loading) return
    setError('')
    if (!email.trim()) { setError('يرجى إدخال البريد الإلكتروني'); return }
    if (!adminPass)    { setError('يرجى إدخال كلمة المرور'); return }
    setLoading(true)
    try {
      const res = await api.superLogin(email.trim(), adminPass)
      setToken(res.token); setStoreId('super'); setIsSuper(true)
      navigate('/admin', { replace: true })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'البريد الإلكتروني أو كلمة المرور غير صحيحة')
    } finally { setLoading(false) }
  }

  const handleSubmit = tab === 'store' ? handleStoreLogin : handleAdminLogin
  const handleKey = (e: React.KeyboardEvent) => { if (e.key === 'Enter') handleSubmit() }

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

          {/* Tabs */}
          <div className="flex border-b border-slate-100">
            <button
              onClick={() => { setTab('store'); setError('') }}
              className={`flex-1 flex items-center justify-center gap-2 py-4 text-sm font-bold transition-all ${
                tab === 'store'
                  ? 'text-teal-600 border-b-2 border-teal-500 bg-teal-50/60'
                  : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50'
              }`}
            >
              <Icon paths={['M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z', 'M9 22V12h6v10']} size={15} />
              دخول المتجر
            </button>
            <button
              onClick={() => { setTab('admin'); setError('') }}
              className={`flex-1 flex items-center justify-center gap-2 py-4 text-sm font-bold transition-all ${
                tab === 'admin'
                  ? 'text-violet-600 border-b-2 border-violet-500 bg-violet-50/60'
                  : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50'
              }`}
            >
              <Icon paths="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" size={15} />
              دخول الإدارة
            </button>
          </div>

          <div className="p-6 sm:p-8 space-y-5">

            {tab === 'store' ? (
              <>
                {/* Store ID */}
                <div>
                  <label className="block text-sm font-semibold text-slate-600 mb-1.5">معرّف المتجر</label>
                  <Input
                    placeholder="store-123"
                    value={storeId}
                    onValueChange={v => { setStoreIdInput(v); setError('') }}
                    variant="bordered"
                    autoComplete="username"
                    classNames={{
                      inputWrapper: 'border-slate-200 hover:border-teal-400 focus-within:!border-teal-500 bg-slate-50 hover:bg-white h-12 rounded-2xl transition-all',
                      input: 'text-sm font-semibold text-slate-800 placeholder:text-slate-400',
                    }}
                    onKeyDown={handleKey}
                    startContent={
                      <Icon paths={['M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z', 'M9 22V12h6v10']} size={16} className="text-slate-500 flex-shrink-0 ml-2" />
                    }
                  />
                </div>

                {/* Password */}
                <div>
                  <label className="block text-sm font-semibold text-slate-600 mb-1.5">كلمة المرور</label>
                  <Input
                    placeholder="أدخل كلمة المرور"
                    type="password"
                    value={storePass}
                    onValueChange={v => { setStorePass(v); setError('') }}
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
              </>
            ) : (
              <>
                {/* Email */}
                <div>
                  <label className="block text-sm font-semibold text-slate-600 mb-1.5">البريد الإلكتروني</label>
                  <Input
                    placeholder="admin@example.com"
                    type="email"
                    value={email}
                    onValueChange={v => { setEmail(v); setError('') }}
                    variant="bordered"
                    autoComplete="email"
                    classNames={{
                      inputWrapper: 'border-slate-200 hover:border-violet-400 focus-within:!border-violet-500 bg-slate-50 hover:bg-white h-12 rounded-2xl transition-all',
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
                    value={adminPass}
                    onValueChange={v => { setAdminPass(v); setError('') }}
                    variant="bordered"
                    autoComplete="current-password"
                    classNames={{
                      inputWrapper: 'border-slate-200 hover:border-violet-400 focus-within:!border-violet-500 bg-slate-50 hover:bg-white h-12 rounded-2xl transition-all',
                      input: 'text-sm font-semibold text-slate-800 placeholder:text-slate-400',
                    }}
                    onKeyDown={handleKey}
                    startContent={
                      <Icon paths={['M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z', 'M12 7V7a4 4 0 018 0v4H4V7a4 4 0 018 0z']} size={16} className="text-slate-500 flex-shrink-0 ml-2" />
                    }
                  />
                </div>
              </>
            )}

            {/* Error */}
            {error && (
              <div className="flex items-center gap-2.5 bg-red-50 border border-red-200 rounded-2xl px-4 py-3 text-xs font-bold text-red-600 animate-in fade-in duration-300">
                <Icon paths="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" size={16} className="flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {/* Submit */}
            <Button
              className={`w-full font-bold text-base h-12 text-white shadow-lg rounded-2xl hover:opacity-95 active:scale-[0.98] transition-all ${
                tab === 'store'
                  ? 'bg-gradient-to-r from-teal-500 to-cyan-500 shadow-teal-500/25'
                  : 'bg-gradient-to-r from-violet-500 to-purple-500 shadow-violet-500/25'
              }`}
              isLoading={loading}
              onPress={handleSubmit}
            >
              {loading
                ? <Spinner size="sm" color="white" />
                : tab === 'store' ? 'دخول لوحة المتجر' : 'دخول لوحة الإدارة'
              }
            </Button>
          </div>
        </div>

        {/* Footer */}
        <div className="text-center mt-6">
          <p className="text-[11px] text-slate-400 font-medium">
            سلّابوت — المساعد الذكي لمتاجر سلة © {new Date().getFullYear()}
          </p>
        </div>
      </div>
    </div>
  )
}
