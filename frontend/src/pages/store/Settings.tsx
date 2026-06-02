import { useEffect, useState } from 'react'
import {
  Card, CardBody, CardHeader,
  Button,
  Divider, Chip, Spinner,
} from '@heroui/react'
import { api, AIConfig, TokenStatus } from '../../api'
import { TextField } from '../../components/ui'

interface Props { storeId: string }

type ProviderKey = 'groq' | 'anthropic' | 'openai'

const PROVIDERS: {
  key: ProviderKey
  label: string
  short: string
  placeholder: string
  color: string  // tailwind text/bg color
}[] = [
  { key: 'groq',      label: 'Groq',      short: 'Llama 3.3', placeholder: 'gsk_...',           color: 'orange' },
  { key: 'anthropic', label: 'Anthropic', short: 'Claude',    placeholder: 'sk-ant-api03-...',  color: 'violet' },
  { key: 'openai',    label: 'OpenAI',    short: 'GPT-4o',    placeholder: 'sk-proj-...',       color: 'emerald' },
]

const MODEL_PRESETS: Record<ProviderKey, string[]> = {
  groq:      ['llama-3.3-70b-versatile', 'llama-3.1-70b-versatile', 'mixtral-8x7b-32768'],
  anthropic: ['claude-sonnet-4-6', 'claude-3-5-haiku-20241022', 'claude-opus-4-5'],
  openai:    ['gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo'],
}

// HeroUI doesn't accept Tailwind class names from string template, so map explicit classes
const PROVIDER_STYLES: Record<string, { active: string; dot: string }> = {
  orange:  { active: 'bg-orange-500/15 border-orange-500/50 text-orange-300',  dot: 'bg-orange-400'  },
  violet:  { active: 'bg-violet-500/15 border-violet-500/50 text-violet-300',  dot: 'bg-violet-400'  },
  emerald: { active: 'bg-emerald-500/15 border-emerald-500/50 text-emerald-300', dot: 'bg-emerald-400' },
}

export default function Settings({ storeId }: Props) {
  // AI Config
  const [cfg, setCfg] = useState<Partial<AIConfig>>({})
  const [provider, setProvider] = useState<ProviderKey>('groq')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [botName, setBotName] = useState('')
  const [storeType, setStoreType] = useState<'printing' | 'general'>('general')
  const [aiLoading, setAiLoading] = useState(false)
  const [aiSaving, setAiSaving] = useState(false)
  const [aiMsg, setAiMsg] = useState('')

  // Password
  const [curPass, setCurPass] = useState('')
  const [newPass, setNewPass] = useState('')
  const [confirmPass, setConfirmPass] = useState('')
  const [passLoading, setPassLoading] = useState(false)
  const [passMsg, setPassMsg] = useState('')

  // Token
  const [tokenStatus, setTokenStatus] = useState<TokenStatus | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [tokenMsg, setTokenMsg] = useState('')

  useEffect(() => { loadSettings() }, [storeId])

  async function loadSettings() {
    setAiLoading(true)
    try {
      const [ai, tok] = await Promise.all([
        api.getAI(storeId),
        api.tokenStatus(storeId),
      ])
      setCfg(ai)
      setProvider((ai.provider !== 'env' ? ai.provider : 'groq') as ProviderKey)
      setBotName(ai.bot_name || '')
      setModel(ai.ai_model || '')
      setStoreType((ai.store_type === 'printing' ? 'printing' : 'general'))
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
        store_type:        storeType,
      }
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
    if (newPass.length < 6)      { setPassMsg('كلمة المرور يجب أن تكون 6 أحرف على الأقل'); return }
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
    setRefreshing(true); setTokenMsg('')
    try {
      const res = await api.refreshToken(storeId)
      setTokenStatus(res)
      setTokenMsg('✅ تم تجديد التوكن بنجاح')
    } catch (e: unknown) {
      setTokenMsg(e instanceof Error ? e.message : 'فشل التجديد')
    } finally { setRefreshing(false) }
  }

  const currentProvider = PROVIDERS.find(p => p.key === provider)!
  const modelSuggestions = MODEL_PRESETS[provider] || []
  const isKeySaved = Boolean(
    (provider === 'groq'      && cfg.groq_api_key)      ||
    (provider === 'anthropic' && cfg.anthropic_api_key) ||
    (provider === 'openai'    && cfg.openai_api_key)
  )

  // Token UI helpers
  const tokenStatusInfo = (() => {
    if (!tokenStatus) return null
    const map: Record<string, { color: 'success' | 'warning' | 'danger' | 'default'; label: string; dot: string }> = {
      ok:       { color: 'success', label: 'صالح',           dot: 'bg-emerald-400'  },
      warning:  { color: 'warning', label: 'ينتهي قريباً',   dot: 'bg-amber-400'    },
      critical: { color: 'danger',  label: 'حرج — أقل من يوم', dot: 'bg-red-400'    },
      expired:  { color: 'danger',  label: 'منتهي',          dot: 'bg-red-400'      },
      unknown:  { color: 'default', label: 'غير معروف',      dot: 'bg-slate-400'    },
    }
    return map[tokenStatus.status] || map.unknown
  })()

  return (
    <div className="p-6 space-y-5 max-w-2xl mx-auto" dir="rtl">
      <header>
        <h1 className="text-xl font-bold text-foreground">الإعدادات</h1>
        <p className="text-sm text-default-500 mt-1">إدارة المساعد الذكي والأمان والاتصال بسلة</p>
      </header>

      {/* ════════════ AI Settings ════════════ */}
      <Card className="bg-content1 border border-divider shadow-sm">
        <CardHeader className="px-5 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-blue-400" />
            <h2 className="font-bold text-sm">إعدادات الذكاء الاصطناعي</h2>
          </div>
          {!aiLoading && cfg.provider && cfg.provider !== 'env' && (
            <Chip size="sm" color="success" variant="flat">مُعدّ</Chip>
          )}
          {!aiLoading && cfg.provider === 'env' && (
            <Chip size="sm" color="default" variant="flat">يستخدم env</Chip>
          )}
        </CardHeader>
        <Divider />
        {aiLoading ? (
          <CardBody className="flex items-center justify-center py-10">
            <Spinner color="primary" />
          </CardBody>
        ) : (
          <CardBody className="px-5 py-6 space-y-6">

            {/* Provider grid */}
            <div className="space-y-2">
              <label className="text-xs font-semibold text-default-500 px-0.5">المزوّد</label>
              <div className="grid grid-cols-3 gap-2">
                {PROVIDERS.map(p => {
                  const isActive = provider === p.key
                  const styles = PROVIDER_STYLES[p.color]
                  return (
                    <button
                      key={p.key}
                      onClick={() => { setProvider(p.key); setApiKey('') }}
                      className={`
                        relative flex flex-col items-center gap-1 py-3 px-2 rounded-xl border text-center
                        transition-all duration-150
                        ${isActive
                          ? styles.active
                          : 'bg-content2 border-divider text-default-400 hover:border-slate-500 hover:text-foreground'
                        }
                      `}
                    >
                      <span className="font-bold text-sm">{p.label}</span>
                      <span className="text-[10px] opacity-70">{p.short}</span>
                      {isActive && (
                        <span className={`absolute top-1.5 left-1.5 w-1.5 h-1.5 rounded-full ${styles.dot}`} />
                      )}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* API Key */}
            <TextField
              label="مفتاح API"
              type="password"
              value={apiKey}
              onChange={setApiKey}
              placeholder={isKeySaved ? '••••••••• (محفوظ — اتركه فارغاً للإبقاء)' : currentProvider.placeholder}
              description={isKeySaved
                ? `مفتاح ${currentProvider.label} محفوظ بالفعل`
                : `الصيغة: ${currentProvider.placeholder}`}
              dir="ltr"
            />

            {/* Model */}
            <div className="space-y-2">
              <TextField
                label="الموديل"
                value={model}
                onChange={setModel}
                placeholder={modelSuggestions[0] || 'اسم الموديل'}
                dir="ltr"
              />
              <div className="flex flex-wrap gap-1.5 pt-1">
                {modelSuggestions.map(m => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setModel(m)}
                    className={`
                      text-[11px] px-2.5 py-1 rounded-lg border transition-colors font-mono
                      ${model === m
                        ? 'bg-primary/15 border-primary/40 text-primary'
                        : 'bg-content2 border-divider text-default-400 hover:text-foreground hover:border-slate-500'
                      }
                    `}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>

            {/* Bot name */}
            <TextField
              label="اسم البوت"
              value={botName}
              onChange={setBotName}
              placeholder="مساعد المتجر"
            />

            {/* Store type — gates printing features */}
            <div>
              <label className="block text-sm font-semibold text-foreground mb-2">
                نوع المتجر
              </label>
              <div className="grid grid-cols-2 gap-2">
                {([
                  { key: 'general',  title: 'متجر عام',   desc: 'منتجات عامة (عبايات، أحذية، إلخ)', icon: '🛍️' },
                  { key: 'printing', title: 'متجر طباعة', desc: 'حاسبات الأسعار وعروض الطباعة',     icon: '🖨️' },
                ] as const).map(opt => {
                  const active = storeType === opt.key
                  return (
                    <button
                      key={opt.key}
                      type="button"
                      onClick={() => setStoreType(opt.key)}
                      className={`text-right rounded-xl border p-3 transition-all ${
                        active
                          ? 'border-blue-500 bg-blue-500/10 ring-1 ring-blue-500/40'
                          : 'border-divider bg-content2 hover:border-blue-500/40'
                      }`}
                    >
                      <div className="flex items-center gap-2 font-bold text-sm text-foreground">
                        <span>{opt.icon}</span>{opt.title}
                      </div>
                      <div className="text-[11px] text-foreground-500 mt-1 leading-relaxed">{opt.desc}</div>
                    </button>
                  )
                })}
              </div>
              <p className="text-[11px] text-foreground-400 mt-2 leading-relaxed">
                {storeType === 'printing'
                  ? '✅ ميزات الطباعة مفعّلة: حاسبات الأسعار، عروض الأسعار، تسعير العلب، والتحويل للموظف.'
                  : 'ميزات الطباعة مخفية. فعّل "متجر طباعة" فقط إذا كان متجرك يقدّم خدمات طباعة.'}
              </p>
            </div>

            {aiMsg && (
              <div className={`rounded-lg p-3 text-sm border ${
                aiMsg.startsWith('✅')
                  ? 'bg-success/10 border-success/20 text-success'
                  : 'bg-danger/10 border-danger/20 text-danger'
              }`}>
                {aiMsg}
              </div>
            )}

            <Button
              color="primary"
              isLoading={aiSaving}
              onPress={saveAI}
              className="w-full font-bold h-11 bg-gradient-to-r from-blue-600 to-indigo-600 shadow-lg shadow-blue-500/20"
            >
              {aiSaving ? '' : 'حفظ إعدادات AI'}
            </Button>
          </CardBody>
        )}
      </Card>

      {/* ════════════ Token Status ════════════ */}
      {tokenStatus && (
        <Card className="bg-content1 border border-divider shadow-sm">
          <CardHeader className="px-5 py-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${tokenStatusInfo?.dot || 'bg-slate-400'}`} />
              <h2 className="font-bold text-sm">حالة توكن سلة</h2>
            </div>
            {tokenStatusInfo && (
              <Chip size="sm" color={tokenStatusInfo.color} variant="flat">
                {tokenStatusInfo.label}
              </Chip>
            )}
          </CardHeader>
          <Divider />
          <CardBody className="px-5 py-4 space-y-3">

            {tokenStatus.days_remaining !== null && tokenStatus.days_remaining !== undefined && (
              <Row label="الأيام المتبقية">
                <span className={`text-sm font-bold ${
                  tokenStatus.days_remaining > 7  ? 'text-emerald-400' :
                  tokenStatus.days_remaining > 0  ? 'text-amber-400'   : 'text-red-400'
                }`}>
                  {tokenStatus.days_remaining > 0 ? `${tokenStatus.days_remaining} يوم` : 'انتهى'}
                </span>
              </Row>
            )}

            {tokenStatus.expires_at && (
              <Row label="تاريخ الانتهاء">
                <span className="text-sm text-default-300 font-mono">
                  {tokenStatus.expires_at.slice(0, 10)}
                </span>
              </Row>
            )}

            <Row label="Refresh Token">
              <Chip size="sm" variant="flat" color={tokenStatus.has_refresh ? 'success' : 'danger'}>
                {tokenStatus.has_refresh ? 'متوفر' : 'غير موجود'}
              </Chip>
            </Row>

            {tokenStatus.message && (
              <div className="bg-content2 border border-divider rounded-lg p-3 text-xs text-default-300 leading-relaxed">
                {tokenStatus.message}
              </div>
            )}

            {tokenMsg && (
              <div className={`rounded-lg p-3 text-sm border ${
                tokenMsg.startsWith('✅')
                  ? 'bg-success/10 border-success/20 text-success'
                  : 'bg-danger/10 border-danger/20 text-danger'
              }`}>
                {tokenMsg}
              </div>
            )}

            <Button
              color="primary"
              variant="flat"
              isLoading={refreshing}
              isDisabled={!tokenStatus.has_refresh}
              onPress={refreshToken}
              className="w-full font-semibold h-10"
              startContent={
                !refreshing && (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="23 4 23 10 17 10"/>
                    <polyline points="1 20 1 14 7 14"/>
                    <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/>
                  </svg>
                )
              }
            >
              {refreshing ? '' : 'تجديد التوكن يدوياً'}
            </Button>
          </CardBody>
        </Card>
      )}

      {/* ════════════ Change Password ════════════ */}
      <Card className="bg-content1 border border-divider shadow-sm">
        <CardHeader className="px-5 py-4 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-amber-400" />
          <h2 className="font-bold text-sm">تغيير كلمة المرور</h2>
        </CardHeader>
        <Divider />
        <CardBody className="px-5 py-6 space-y-5">
          <TextField
            label="كلمة المرور الحالية" type="password"
            value={curPass} onChange={setCurPass}
            placeholder="أدخل كلمة المرور الحالية"
          />
          <TextField
            label="كلمة المرور الجديدة" type="password"
            value={newPass} onChange={setNewPass}
            placeholder="٦ أحرف على الأقل"
          />
          <TextField
            label="تأكيد كلمة المرور الجديدة" type="password"
            value={confirmPass} onChange={setConfirmPass}
            placeholder="أعد إدخال كلمة المرور الجديدة"
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
            color="warning"
            variant="flat"
            isLoading={passLoading}
            onPress={changePassword}
            isDisabled={!curPass || !newPass || !confirmPass}
            className="w-full font-semibold h-11"
          >
            {passLoading ? '' : 'تغيير كلمة المرور'}
          </Button>
        </CardBody>
      </Card>
    </div>
  )
}

// ── Row helper for the token-status card ─────────────────────────────────────
function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-sm text-default-400">{label}</span>
      {children}
    </div>
  )
}
