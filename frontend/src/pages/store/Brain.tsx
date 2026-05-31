import { useEffect, useState } from 'react'
import {
  Card, CardBody, CardHeader,
  Button, Textarea, Spinner, Chip, Divider,
} from '@heroui/react'
import { api, BrainData } from '../../api'

interface Props { storeId: string }

function Icon({ paths, size = 14, className = '' }: { paths: string | string[]; size?: number; className?: string }) {
  const arr = Array.isArray(paths) ? paths : [paths]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={className}>
      {arr.map((d, i) => <path key={i} d={d} />)}
    </svg>
  )
}

const KNOWLEDGE_PLACEHOLDER = `مثال:
• ساعات العمل: من السبت إلى الخميس، ٩ صباحاً - ٦ مساءً
• سياسة الإرجاع: استبدال خلال ٧ أيام بشرط عدم الاستخدام
• الشحن: مجاناً للطلبات فوق ٢٠٠ ريال، يستغرق ٢-٤ أيام
• طرق الدفع: مدى، فيزا، Apple Pay، تحويل بنكي
• للتصميم المخصص: نقبل ملفات AI/PSD/PDF بدقة ٣٠٠ DPI
• خصم خاص للطلبات الكبيرة (+٥٠٠٠ قطعة): تواصل مع المبيعات

اكتب أي معلومات مهمة عن متجرك تريد البوت يعرفها ويستخدمها في الردود.`

export default function Brain({ storeId }: Props) {
  const [data, setData] = useState<BrainData | null>(null)
  const [customText, setCustomText] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [retraining, setRetraining] = useState(false)
  const [msg, setMsg] = useState('')
  const [showPreview, setShowPreview] = useState(false)

  useEffect(() => { load() }, [storeId])

  async function load() {
    setLoading(true)
    try {
      const d = await api.getBrain(storeId)
      setData(d)
      setCustomText(d.custom_knowledge || '')
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  async function save() {
    setSaving(true); setMsg('')
    try {
      await api.setBrain(storeId, customText)
      setMsg('✅ تم حفظ الذاكرة المخصصة — البوت سيستخدمها فوراً')
      await load()
    } catch (e: unknown) {
      setMsg(e instanceof Error ? e.message : 'خطأ في الحفظ')
    } finally { setSaving(false) }
  }

  async function retrain() {
    setRetraining(true); setMsg('')
    try {
      const r = await api.retrainBrain(storeId)
      setMsg(`✅ ${r.message} (${r.products_synced} منتج، ${r.categories} تصنيف)`)
      await load()
    } catch (e: unknown) {
      setMsg(e instanceof Error ? e.message : 'فشل التحديث')
    } finally { setRetraining(false) }
  }

  if (loading || !data) {
    return <div className="flex items-center justify-center min-h-[400px]"><Spinner color="primary" /></div>
  }

  const ov = data.overview
  const usagePercent = Math.round((data.knowledge_chars / data.knowledge_budget) * 100)

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5" dir="rtl">

      {/* Header */}
      <header className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-foreground flex items-center gap-2">
            🧠 ذاكرة الـ AI
          </h1>
          <p className="text-sm text-default-500 mt-1">
            ماذا يعرف البوت عن متجرك — وكيف يمكنك تعليمه أكثر
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            color="warning" variant="flat" isLoading={retraining}
            onPress={retrain}
            startContent={!retraining && (
              <Icon paths="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            )}
            className="font-bold h-11"
          >
            {retraining ? '' : 'ذاكر المتجر (مزامنة كاملة)'}
          </Button>
        </div>
      </header>

      {msg && (
        <div className={`rounded-lg p-3 text-sm border ${
          msg.startsWith('✅')
            ? 'bg-success/10 border-success/20 text-success'
            : 'bg-danger/10 border-danger/20 text-danger'
        }`}>{msg}</div>
      )}

      {/* ════════════ STORE PROFILE (from Salla /store/info) ════════════ */}
      {data.store_info && data.store_info.name && (
        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-blue-400" />
              <h2 className="font-bold text-sm">ملف المتجر (من سلة)</h2>
            </div>
            {data.store_info.verified && (
              <Chip size="sm" color="success" variant="flat">✓ موثّق</Chip>
            )}
          </CardHeader>
          <Divider />
          <CardBody className="px-5 py-4">
            <div className="flex items-start gap-4">
              {data.store_info.avatar && (
                <img
                  src={data.store_info.avatar}
                  alt={data.store_info.name}
                  className="w-16 h-16 rounded-2xl object-cover border border-divider flex-shrink-0"
                  onError={e => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
                />
              )}
              <div className="flex-1 min-w-0 space-y-1.5">
                <h3 className="font-bold text-base text-foreground">{data.store_info.name}</h3>
                {data.store_info.description && (
                  <p className="text-xs text-default-400 leading-relaxed">
                    {data.store_info.description}
                  </p>
                )}
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {data.store_info.entity && (
                    <Chip size="sm" variant="flat" color="default">
                      {data.store_info.entity === 'company' ? 'شركة'
                       : data.store_info.entity === 'person' ? 'متجر فردي'
                       : data.store_info.entity === 'charity' ? 'جمعية خيرية'
                       : data.store_info.entity === 'firm' ? 'مؤسسة'
                       : data.store_info.entity}
                    </Chip>
                  )}
                  {data.store_info.plan && (
                    <Chip size="sm" variant="flat" color="primary">خطة {data.store_info.plan}</Chip>
                  )}
                  {data.store_info.currency && (
                    <Chip size="sm" variant="flat" color="warning">{data.store_info.currency}</Chip>
                  )}
                </div>
                {(data.store_info.domain || data.store_info.email) && (
                  <div className="text-xs text-default-500 pt-2 space-y-0.5">
                    {data.store_info.domain && <div>🌐 {data.store_info.domain}</div>}
                    {data.store_info.email  && <div>📧 {data.store_info.email}</div>}
                  </div>
                )}
                {data.store_info.social && Object.entries(data.store_info.social)
                    .filter(([, v]) => v && !['https://', 'http://'].includes(String(v))).length > 0 && (
                  <div className="flex flex-wrap gap-1 pt-2">
                    {data.store_info.social.whatsapp && (
                      <Chip size="sm" variant="flat" color="success">💬 {data.store_info.social.whatsapp}</Chip>
                    )}
                    {(['twitter', 'instagram', 'facebook', 'snapchat', 'youtube', 'telegram', 'maroof', 'appstore_link', 'googleplay_link'] as const)
                      .filter(k => data.store_info!.social![k] && !['https://', 'http://'].includes(String(data.store_info!.social![k])))
                      .map(k => (
                        <Chip key={k} size="sm" variant="flat" color="default">
                          {({
                            twitter: '🐦 X',
                            instagram: '📷 IG',
                            facebook: '📘 FB',
                            snapchat: '👻 Snap',
                            youtube: '▶️ YT',
                            telegram: '✈️ TG',
                            maroof: '🏅 معروف',
                            appstore_link: '🍎 iOS',
                            googleplay_link: '🤖 Play',
                          } as Record<string, string>)[k]}
                        </Chip>
                      ))}
                  </div>
                )}
                {data.store_info.licenses && (data.store_info.licenses.commercial_number || data.store_info.licenses.tax_number) && (
                  <div className="flex flex-wrap gap-1 pt-2 text-[10px] text-default-500">
                    {data.store_info.licenses.commercial_number && <span>📋 س.ت: {data.store_info.licenses.commercial_number}</span>}
                    {data.store_info.licenses.tax_number && <span> · 🧾 ضريبي: {data.store_info.licenses.tax_number}</span>}
                  </div>
                )}
              </div>
            </div>
          </CardBody>
        </Card>
      )}

      {/* ════════════ SHIPPING COMPANIES ════════════ */}
      {data.shipping_companies && data.shipping_companies.length > 0 && (
        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-orange-400" />
              <h2 className="font-bold text-sm">🚚 شركات الشحن المتاحة</h2>
            </div>
            <Chip size="sm" variant="flat" color="default">
              {data.shipping_companies.length} شركة
            </Chip>
          </CardHeader>
          <Divider />
          <CardBody className="px-5 py-4">
            <div className="flex flex-wrap gap-2">
              {data.shipping_companies.map(c => (
                <Chip
                  key={c.id ?? c.name}
                  size="md" variant="flat"
                  color={c.activation_type === 'api' ? 'success' : 'default'}
                  startContent={
                    <span className="text-xs">
                      {c.activation_type === 'api' ? '🔗' : '📝'}
                    </span>
                  }
                  className="font-semibold pl-1"
                >
                  {c.name}
                </Chip>
              ))}
            </div>
            <p className="text-[11px] text-default-500 mt-3">
              <span className="text-emerald-400">🔗 API</span> = مفعّل تلقائياً عبر سلة ·
              <span className="text-default-400 mr-1">📝 يدوي</span> = يربطه التاجر يدوياً
            </p>
          </CardBody>
        </Card>
      )}

      {/* ════════════ STATS GRID ════════════ */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          icon="📦" label="المنتجات المتاحة"
          value={ov.available_products.toLocaleString()}
          sub={ov.total_products !== ov.available_products ? `من ${ov.total_products}` : ''}
          color="blue"
        />
        <StatCard
          icon="📁" label="التصنيفات"
          value={ov.categories.toLocaleString()}
          color="emerald"
        />
        <StatCard
          icon="💰" label="نطاق الأسعار"
          value={ov.min_price !== null ? `${ov.min_price}-${ov.max_price}` : '—'}
          sub={ov.min_price !== null ? `${ov.currency} (متوسط ${ov.avg_price})` : ''}
          color="amber"
        />
        <StatCard
          icon="📝" label="حجم الذاكرة"
          value={`${(data.knowledge_chars / 1000).toFixed(1)}K`}
          sub={`${usagePercent}% من السعة`}
          color={usagePercent > 90 ? 'rose' : usagePercent > 70 ? 'amber' : 'emerald'}
        />
      </div>

      {/* ════════════ TOP CATEGORIES ════════════ */}
      {ov.top_categories.length > 0 && (
        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
            <h2 className="font-bold text-sm">أكبر التصنيفات في متجرك</h2>
          </CardHeader>
          <Divider />
          <CardBody className="px-5 py-4">
            <div className="flex flex-wrap gap-2">
              {ov.top_categories.map(c => (
                <Chip key={c.name} variant="flat" color="primary" size="md" className="font-semibold">
                  {c.name} <span className="text-xs opacity-70">({c.count})</span>
                </Chip>
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      {/* ════════════ CUSTOM KNOWLEDGE EDITOR ════════════ */}
      <Card className="bg-content1 border border-divider">
        <CardHeader className="px-5 py-4 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-violet-400" />
            <h2 className="font-bold text-sm">معلومات مخصصة (تكتبها أنت — البوت يحفظها)</h2>
          </div>
          <Chip size="sm" variant="flat" color="default">
            {customText.length.toLocaleString()} / 3,000 حرف
          </Chip>
        </CardHeader>
        <Divider />
        <CardBody className="px-5 py-5 space-y-3">
          <p className="text-xs text-default-500 leading-relaxed">
            اكتب هنا أي معلومات مهمة تريد البوت أن يعرفها: سياسات، أوقات العمل،
            طرق الدفع، الشحن، الخصومات الخاصة، أسئلة متكررة، إلخ.
            البوت سيراها قبل كل رد على العميل.
          </p>
          <Textarea
            value={customText}
            onValueChange={setCustomText}
            placeholder={KNOWLEDGE_PLACEHOLDER}
            variant="bordered"
            minRows={10}
            maxRows={20}
            classNames={{
              inputWrapper: 'border-divider bg-content2',
              input: 'text-sm leading-relaxed',
            }}
          />
          <div className="flex justify-end">
            <Button
              color="primary" isLoading={saving} onPress={save}
              isDisabled={customText.length > 3000}
              className="font-bold h-11 bg-gradient-to-r from-blue-600 to-indigo-600 shadow-lg shadow-blue-500/20"
            >
              {saving ? '' : 'حفظ الذاكرة'}
            </Button>
          </div>
        </CardBody>
      </Card>

      {/* ════════════ KNOWLEDGE PREVIEW ════════════ */}
      <Card className="bg-content1 border border-divider">
        <CardHeader className="px-5 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-cyan-400" />
            <h2 className="font-bold text-sm">🔍 ما يراه البوت بالفعل (Preview)</h2>
          </div>
          <Button
            size="sm" variant="flat" color="default"
            onPress={() => setShowPreview(p => !p)}
          >
            {showPreview ? 'إخفاء' : 'عرض'}
          </Button>
        </CardHeader>
        {showPreview && (
          <>
            <Divider />
            <CardBody className="px-5 py-4">
              <pre className="text-[11px] text-default-400 bg-content2 p-4 rounded-lg overflow-x-auto leading-relaxed whitespace-pre-wrap font-mono max-h-[500px] overflow-y-auto">
{data.knowledge_preview || '(لا توجد معلومات بعد — اضغط "ذاكر المتجر" لتحميل المنتجات)'}
              </pre>
            </CardBody>
          </>
        )}
      </Card>

      {/* Tips */}
      <Card className="bg-blue-500/5 border border-blue-500/20">
        <CardBody className="px-5 py-4">
          <h3 className="text-sm font-bold text-blue-300 mb-2 flex items-center gap-2">
            💡 نصائح لذاكرة فعّالة
          </h3>
          <ul className="text-xs text-default-400 space-y-1.5 leading-relaxed">
            <li>• الـ AI يحفظ كل ما تكتبه ويستخدمه قبل الرد على أي سؤال</li>
            <li>• استخدم نقاط قصيرة بدل فقرات طويلة — أوضح للبوت</li>
            <li>• لو غيّرت منتجاتك من سلة، اضغط "ذاكر المتجر" لتحديث الذاكرة</li>
            <li>• الذاكرة المخصصة محفوظة في قاعدة البيانات وتبقى بعد كل deploy</li>
          </ul>
        </CardBody>
      </Card>
    </div>
  )
}

function StatCard({ icon, label, value, sub, color }: {
  icon: string; label: string; value: string; sub?: string;
  color: 'blue' | 'emerald' | 'amber' | 'rose'
}) {
  const colors: Record<string, string> = {
    blue:    'border-blue-500/20 bg-blue-500/5',
    emerald: 'border-emerald-500/20 bg-emerald-500/5',
    amber:   'border-amber-500/20 bg-amber-500/5',
    rose:    'border-rose-500/20 bg-rose-500/5',
  }
  const valueColors: Record<string, string> = {
    blue: 'text-blue-300', emerald: 'text-emerald-300',
    amber: 'text-amber-300', rose: 'text-rose-300',
  }
  return (
    <div className={`rounded-2xl border p-4 ${colors[color]}`}>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xl">{icon}</span>
        <span className="text-[11px] text-default-400 font-medium">{label}</span>
      </div>
      <div className={`text-xl md:text-2xl font-black ${valueColors[color]} leading-tight`}>{value}</div>
      {sub && <div className="text-[10px] text-default-500 mt-1">{sub}</div>}
    </div>
  )
}
