import { useEffect, useState } from 'react'
import {
  Card, CardBody, CardHeader,
  Button, Input, Select, SelectItem,
  Divider, Chip, Spinner,
} from '@heroui/react'
import { api, AIConfig } from '../../api'

interface Props { storeId: string }

const PROVIDERS = [
  { key: 'groq',      label: 'Groq (Llama)',        hint: 'gsk_...',          placeholder: 'gsk_...' },
  { key: 'anthropic', label: 'Anthropic (Claude)',   hint: 'sk-ant-...',       placeholder: 'sk-ant-api03-...' },
  { key: 'openai',    label: 'OpenAI (GPT)',         hint: 'sk-proj-...',      placeholder: 'sk-proj-...' },
] as const

const MODEL_PRESETS: Record<string, string[]> = {
  groq:      ['llama-3.3-70b-versatile', 'llama-3.1-70b-versatile', 'mixtral-8x7b-32768'],
  anthropic: ['claude-sonnet-4-6', 'claude-3-5-haiku-20241022', 'claude-opus-4-5'],
  openai:    ['gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo'],
}

export default function Settings({ storeId }: Props) {
  // AI Config state
  const [cfg, setCfg] = useState<Partial<AIConfig>>({})
  const [provider, setProvider] = useState<'groq' | 'anthropic' | 'openai'>('groq')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [botName, setBotName] = useState('')
  const [aiLoading, setAiLoading] = useState(false)
  const [aiSaving, setAiSaving] = useState(false)
  const [aiMsg, setAiMsg] = useState('')

  // Password state
  const [curPass, setCurPass] = useState('')
  const [newPass, setNewPass] = useState('')
  const [confirmPass, setConfirmPass] = useState('')
  const [passLoading, setPassLoading] = useState(false)
  const [passMsg, setPassMsg] = useState('')

  // Token status
  const [tokenStatus, setTokenStatus] = useState<{ connected: boolean; health: string; days_left?: number } | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => { loadSettings() }, [storeId])

  async function loadSettings() {
    setAiLoading(true)
    try {
      const [ai, tok] = await Promise.all([
        api.getAI(storeId),
        api.tokenStatus(storeId),
      ])
      setCfg(ai)
      setProvider((ai.provider !== 'env' ? ai.provider : 'groq') as typeof provider)
      setBotName(ai.bot_name || '')
      setModel(ai.ai_model || '')
      // Don't prefill API key (it's masked)
      setTokenStatus(tok)
    } catch (e) { console.error(e) }
    finally { setAiLoading(false) }
  }

  async function saveAI() {
    setAiSaving(true); setAiMsg('')
    try {
      const payload: Record<string, string> = {
        groq_api_key:      '',
        anthropic_api_key: '',
        openai_api_key:    '',
        ai_model:          model,
        bot_name:          botName,
      }
      // Only send the key for the selected provider
      if (apiKey.trim()) {
        if (provider === 'groq')      payload.groq_api_key      = apiKey.trim()
        if (provider === 'anthropic') payload.anthropic_api_key = apiKey.trim()
        if (provider === 'openai')    payload.openai_api_key    = apiKey.trim()
      }
      await api.setAI(storeId, payload)
      setAiMsg('✅ تم حفظ إعدادات الذكاء الاصطناعي')
      setApiKey('')
      loadSettings()
    } catch (e: unknown) {
      setAiMsg(e instanceof Error ? e.message : 'خطأ في الحفظ')
    } finally { setAiSaving(false) }
  }

  async function changePassword() {
    if (newPass !== confirmPass) { setPassMsg('كلمة المرور الجديدة لا تتطابق'); return }
    if (newPass.length < 6) { setPassMsg('كلمة المرور يجب أن تكون 6 أحرف على الأقل'); return }
    setPassLoading(true); setPassMsg('')
    try {
      await api.changePassword(storeId, curPass, newPass)
      setPassMsg('✅ تم تغيير كلمة المرور')
      setCurPass(''); setNewPass(''); setConfirmPass('')
    } catch (e: unknown) {
      setPassMsg(e instanceof Error ? e.message : 'خطأ')
    } finally { setPassLoading(false) }
  }

  async function refreshToken() {
    setRefreshing(true)
    try {
      const res = await api.refreshToken(storeId)
      setTokenStatus(res)
    } catch (e: unknown) {
      console.error(e)
    } finally { setRefreshing(false) }
  }

  const currentProvider = PROVIDERS.find(p => p.key === provider)!
  const modelSuggestions = MODEL_PRESETS[provider] || []
  const isKeySaved = Boolean(
    (provider === 'groq'      && cfg.groq_api_key)      ||
    (provider === 'anthropic' && cfg.anthropic_api_key) ||
    (provider === 'openai'    && cfg.openai_api_key)
  )

  return (
    <div className="p-6 space-y-6 max-w-2xl">
      <h1 className="text-xl font-bold text-foreground">الإعدادات</h1>

      {/* ── AI Settings ── */}
      <Card className="bg-content1 border border-divider">
        <CardHeader className="px-5 py-4">
          <h2 className="font-bold text-sm flex items-center gap-2">
            إعدادات الذكاء الاصطناعي
            {!aiLoading && cfg.provider && cfg.provider !== 'env' && (
              <Chip size="sm" color="success" variant="flat">مُعدّ</Chip>
            )}
            {!aiLoading && cfg.provider === 'env' && (
              <Chip size="sm" color="default" variant="flat">يستخدم env</Chip>
            )}
          </h2>
        </CardHeader>
        <Divider />
        {aiLoading ? (
          <CardBody className="flex items-center justify-center py-10">
            <Spinner color="primary" />
          </CardBody>
        ) : (
          <CardBody className="px-5 py-5 space-y-4">
            {/* Provider select */}
            <div className="space-y-1">
              <label className="text-xs text-default-400 font-medium">المزود</label>
              <div className="flex gap-2">
                {PROVIDERS.map(p => (
                  <button
                    key={p.key}
                    onClick={() => { setProvider(p.key); setApiKey('') }}
                    className={`
                      flex-1 py-2 px-3 rounded-xl text-sm font-medium border transition-colors
                      ${provider === p.key
                        ? 'bg-primary/15 border-primary/50 text-primary'
                        : 'bg-content2 border-divider text-default-400 hover:text-foreground'
                      }
                    `}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* API Key */}
            <Input
              label={`${currentProvider.label} API Key`}
              placeholder={isKeySaved ? '••••••••• (محفوظ)' : currentProvider.placeholder}
              type="password"
              value={apiKey}
              onValueChange={setApiKey}
              variant="bordered"
              description={isKeySaved ? 'مفتاح محفوظ — اتركه فارغاً للإبقاء عليه أو أدخل مفتاحاً جديداً' : undefined}
              classNames={{ inputWrapper: 'border-divider' }}
            />

            {/* Model */}
            <div className="space-y-2">
              <Input
                label="الموديل"
                placeholder={modelSuggestions[0] || 'اسم الموديل'}
                value={model}
                onValueChange={setModel}
                variant="bordered"
                classNames={{ inputWrapper: 'border-divider' }}
              />
              <div className="flex flex-wrap gap-1.5">
                {modelSuggestions.map(m => (
                  <button
                    key={m}
                    onClick={() => setModel(m)}
                    className={`
                      text-xs px-2.5 py-1 rounded-lg border transition-colors
                      ${model === m
                        ? 'bg-primary/15 border-primary/40 text-primary'
                        : 'bg-content2 border-divider text-default-400 hover:text-foreground'
                      }
                    `}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>

            {/* Bot name */}
            <Input
              label="اسم البوت"
              placeholder="مساعد المتجر"
              value={botName}
              onValueChange={setBotName}
              variant="bordered"
              classNames={{ inputWrapper: 'border-divider' }}
            />

            {aiMsg && (
              <div className={`rounded-lg p-3 text-sm border ${
                aiMsg.startsWith('✅')
                  ? 'bg-success/10 border-success/20 text-success'
                  : 'bg-danger/10 border-danger/20 text-danger'
              }`}>
                {aiMsg}
              </div>
            )}

            <Button color="primary" isLoading={aiSaving} onPress={saveAI} className="w-full">
              حفظ إعدادات AI
            </Button>
          </CardBody>
        )}
      </Card>

      {/* ── Token Status ── */}
      {tokenStatus && (
        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4">
            <h2 className="font-bold text-sm">حالة توكن سلة</h2>
          </CardHeader>
          <Divider />
          <CardBody className="px-5 py-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-default-400">الحالة</span>
              <Chip
                size="sm"
                color={
                  tokenStatus.health === 'healthy' ? 'success' :
                  tokenStatus.health === 'expiring_soon' ? 'warning' : 'danger'
                }
                variant="flat"
              >
                {tokenStatus.health === 'healthy' ? 'صالح' :
                 tokenStatus.health === 'expiring_soon' ? 'ينتهي قريباً' : 'منتهي'}
              </Chip>
            </div>
            {tokenStatus.days_left !== undefined && (
              <div className="flex items-center justify-between">
                <span className="text-sm text-default-400">الأيام المتبقية</span>
                <span className={`text-sm font-bold ${
                  tokenStatus.days_left > 7 ? 'text-success' :
                  tokenStatus.days_left > 0 ? 'text-warning' : 'text-danger'
                }`}>
                  {tokenStatus.days_left} يوم
                </span>
              </div>
            )}
            <Button
              size="sm"
              variant="flat"
              color="primary"
              isLoading={refreshing}
              onPress={refreshToken}
              className="w-full"
            >
              تجديد التوكن
            </Button>
          </CardBody>
        </Card>
      )}

      {/* ── Change Password ── */}
      <Card className="bg-content1 border border-divider">
        <CardHeader className="px-5 py-4">
          <h2 className="font-bold text-sm">تغيير كلمة المرور</h2>
        </CardHeader>
        <Divider />
        <CardBody className="px-5 py-5 space-y-3">
          <Input
            label="كلمة المرور الحالية"
            type="password"
            value={curPass}
            onValueChange={setCurPass}
            variant="bordered"
            classNames={{ inputWrapper: 'border-divider' }}
          />
          <Input
            label="كلمة المرور الجديدة"
            type="password"
            value={newPass}
            onValueChange={setNewPass}
            variant="bordered"
            classNames={{ inputWrapper: 'border-divider' }}
          />
          <Input
            label="تأكيد كلمة المرور الجديدة"
            type="password"
            value={confirmPass}
            onValueChange={setConfirmPass}
            variant="bordered"
            classNames={{ inputWrapper: 'border-divider' }}
          />
          {passMsg && (
            <div className={`rounded-lg p-3 text-sm border ${
              passMsg.startsWith('✅')
                ? 'bg-success/10 border-success/20 text-success'
                : 'bg-danger/10 border-danger/20 text-danger'
            }`}>
              {passMsg}
            </div>
          )}
          <Button
            color="primary"
            variant="flat"
            isLoading={passLoading}
            onPress={changePassword}
            className="w-full"
          >
            تغيير كلمة المرور
          </Button>
        </CardBody>
      </Card>
    </div>
  )
}
