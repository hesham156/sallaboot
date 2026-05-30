import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Card, CardBody, CardHeader, Input, Button, Chip, Divider } from '@heroui/react'
import { api, setToken, setStoreId, setIsSuper } from '../api'

export default function Login() {
  const { storeId } = useParams<{ storeId?: string }>()
  const navigate = useNavigate()

  const [mode, setMode] = useState<'super' | 'store'>(storeId ? 'store' : 'super')
  const [inputStoreId, setInputStoreId] = useState(storeId || '')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleLogin() {
    setError('')
    setLoading(true)
    try {
      if (mode === 'super') {
        const res = await api.superLogin(password)
        setToken(res.token)
        setStoreId('super')
        setIsSuper(true)
        navigate('/', { replace: true })
      } else {
        if (!inputStoreId.trim()) { setError('أدخل رقم المتجر'); return }
        const res = await api.storeLogin(inputStoreId.trim(), password)
        setToken(res.token)
        setStoreId(res.store_id)
        setIsSuper(false)
        navigate(`/store/${res.store_id}`, { replace: true })
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'خطأ في تسجيل الدخول')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md bg-content1 border border-divider shadow-2xl">
        <CardHeader className="flex flex-col items-center gap-3 pt-8 pb-4">
          {/* Logo */}
          <div className="w-14 h-14 bg-primary rounded-2xl flex items-center justify-center shadow-lg shadow-primary/30">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
          </div>
          <div className="text-center">
            <h1 className="text-xl font-bold text-foreground">بوت المتجر</h1>
            <p className="text-sm text-default-400 mt-1">لوحة تحكم المساعد الذكي</p>
          </div>

          {/* Mode toggle */}
          <div className="flex gap-2 mt-1">
            <Chip
              variant={mode === 'super' ? 'solid' : 'bordered'}
              color="primary"
              className="cursor-pointer"
              onClick={() => { setMode('super'); setError('') }}
            >
              مدير عام
            </Chip>
            <Chip
              variant={mode === 'store' ? 'solid' : 'bordered'}
              color="primary"
              className="cursor-pointer"
              onClick={() => { setMode('store'); setError('') }}
            >
              متجر
            </Chip>
          </div>
        </CardHeader>

        <Divider />

        <CardBody className="gap-4 px-6 py-6">
          {mode === 'store' && (
            <Input
              label="رقم المتجر"
              placeholder="أدخل معرف المتجر"
              value={inputStoreId}
              onValueChange={setInputStoreId}
              variant="bordered"
              classNames={{ label: 'text-default-300', inputWrapper: 'border-divider' }}
              startContent={
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-default-400">
                  <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
                  <polyline points="9 22 9 12 15 12 15 22"/>
                </svg>
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
            classNames={{ label: 'text-default-300', inputWrapper: 'border-divider' }}
            onKeyDown={e => e.key === 'Enter' && handleLogin()}
            startContent={
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-default-400">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
              </svg>
            }
          />

          {error && (
            <div className="bg-danger/10 border border-danger/20 rounded-lg p-3 text-danger text-sm">
              {error}
            </div>
          )}

          <Button
            color="primary"
            className="w-full font-bold text-base h-12 mt-1"
            isLoading={loading}
            onPress={handleLogin}
          >
            {loading ? 'جاري الدخول...' : 'دخول'}
          </Button>

          {mode === 'store' && (
            <p className="text-center text-xs text-default-400 mt-1">
              كلمة المرور الافتراضية هي رقم المتجر
            </p>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
