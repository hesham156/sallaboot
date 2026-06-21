import { useEffect, useState } from 'react'
import { Button, Textarea, Spinner } from '@heroui/react'
import { api, BrainData } from '../../api'
import { PageHeader } from '../../components/ui'

interface Props { storeId: string }

function Icon({ d, size = 14, className = '' }: { d: string | string[]; size?: number; className?: string }) {
  const paths = Array.isArray(d) ? d : [d]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
      className={className}>
      {paths.map((p, i) => <path key={i} d={p} />)}
    </svg>
  )
}

const PLACEHOLDER = `• ساعات العمل: السبت-الخميس ٩ص - ٦م
• سياسة الإرجاع: استبدال خلال ٧ أيام
• الشحن: مجاناً فوق ٢٠٠ ريال، ٢-٤ أيام
• خصومات خاصة: +٥٠٠٠ قطعة → تواصل المبيعات
• للتصميم المخصص: ملفات AI/PSD بدقة ٣٠٠DPI

اكتب أي معلومات تريد البوت يعرفها ويستخدمها في الردود.`

/* ── Small section in left panel ── */
function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <div className="border border-divider rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-3.5 py-2.5 bg-content2/60 border-b border-divider">
        <span className="text-xs font-bold text-foreground">{title}</span>
        {count !== undefined && (
          <span className="text-[10px] font-bold text-default-400 bg-content2 px-2 py-0.5 rounded-md border border-divider">{count}</span>
        )}
      </div>
      <div className="px-3.5 py-3">{children}</div>
    </div>
  )
}

/* ── Inline chips ── */
function Tags({ items, color = '' }: { items: string[]; color?: string }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((t, i) => (
        <span key={i} className={`text-[11px] font-medium px-2 py-0.5 rounded-md border ${
          color || 'bg-content2 border-divider text-default-400'
        }`}>{t}</span>
      ))}
    </div>
  )
}

export default function Brain({ storeId }: Props) {
  const [data, setData]           = useState<BrainData | null>(null)
  const [customText, setCustomText] = useState('')
  const [loading, setLoading]     = useState(true)
  const [saving, setSaving]       = useState(false)
  const [retraining, setRetraining] = useState(false)
  const [msg, setMsg]             = useState('')
  const [showPreview, setShowPreview] = useState(false)

  useEffect(() => { load() }, [storeId])

  async function load() {
    setLoading(true)
    try { const d = await api.getBrain(storeId); setData(d); setCustomText(d.custom_knowledge || '') }
    catch { /* ignore */ } finally { setLoading(false) }
  }

  async function save() {
    setSaving(true); setMsg('')
    try { await api.setBrain(storeId, customText); setMsg('✅ تم حفظ الذاكرة — البوت سيستخدمها فوراً'); await load() }
    catch (e: unknown) { setMsg(e instanceof Error ? e.message : 'خطأ') }
    finally { setSaving(false) }
  }

  async function retrain() {
    setRetraining(true); setMsg('')
    try { const r = await api.retrainBrain(storeId); setMsg(`✅ ${r.message} (${r.products_synced} منتج)`); await load() }
    catch (e: unknown) { setMsg(e instanceof Error ? e.message : 'فشل') }
    finally { setRetraining(false) }
  }

  if (loading || !data) {
    return <div className="flex items-center justify-center h-full"><Spinner color="primary" /></div>
  }

  const ov = data.overview
  const usedPct = Math.min(100, Math.round((data.knowledge_chars / data.knowledge_budget) * 100))

  return (
    <div className="h-full flex flex-col" dir="rtl">

      {/* ── Header ── */}
      <div className="px-6 pt-6 pb-4">
        <PageHeader
          title="ذاكرة الـ AI"
          subtitle="ماذا يعرف البوت عن متجرك — وكيف تعلّمه أكثر"
          icon="M9.5 2A2.5 2.5 0 0112 4.5v15a2.5 2.5 0 01-4.96.44 2.5 2.5 0 01-2.96-3.08 3 3 0 01-.34-5.58 2.5 2.5 0 011.32-4.24A2.5 2.5 0 019.5 2zm5 0A2.5 2.5 0 0012 4.5v15a2.5 2.5 0 004.96.44 2.5 2.5 0 002.96-3.08 3 3 0 00.34-5.58 2.5 2.5 0 00-1.32-4.24A2.5 2.5 0 0014.5 2z"
          actions={
            <Button variant="flat" color="warning" isLoading={retraining} onPress={retrain}
              className="font-bold h-9 text-xs"
              startContent={!retraining && <Icon d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />}>
              {retraining ? '' : 'ذاكر المتجر (مزامنة)'}
            </Button>
          }
        />
      </div>

      {/* ── Toast msg ── */}
      {msg && (
        <div className={`mx-6 mb-3 rounded-xl px-3.5 py-2.5 text-xs border flex items-center gap-2 ${
          msg.startsWith('✅') ? 'bg-success/8 border-success/20 text-success' : 'bg-danger/8 border-danger/20 text-danger'
        }`}>
          {msg.startsWith('✅') ? '✓' : '!'} {msg}
        </div>
      )}

      {/* ── Split layout ── */}
      <div className="flex-1 overflow-hidden flex gap-0 px-6 pb-6">

        {/* ══ LEFT: Store data panels ══ */}
        <div className="w-72 flex-shrink-0 flex flex-col gap-3 overflow-y-auto pl-4">

          {/* Stats row */}
          <div className="grid grid-cols-2 gap-2">
            {[
              { emoji: '📦', label: 'منتج متاح', value: ov.available_products.toLocaleString(), color: 'text-blue-400' },
              { emoji: '📁', label: 'تصنيف',     value: ov.categories.toLocaleString(),          color: 'text-emerald-400' },
              { emoji: '💰', label: 'نطاق الأسعار',
                value: ov.min_price !== null ? `${ov.min_price}–${ov.max_price}` : '—',
                sub: ov.min_price !== null ? ov.currency : '', color: 'text-amber-400' },
              { emoji: '🧠', label: 'الذاكرة',
                value: `${usedPct}%`,
                sub: `${(data.knowledge_chars/1000).toFixed(1)}K حرف`,
                color: usedPct > 90 ? 'text-rose-400' : usedPct > 70 ? 'text-amber-400' : 'text-emerald-400' },
            ].map(s => (
              <div key={s.label} className="bg-content2 rounded-xl border border-divider p-3 space-y-0.5">
                <p className="text-[10px] text-default-400 font-medium">{s.emoji} {s.label}</p>
                <p className={`text-lg font-black leading-tight ${s.color}`}>{s.value}</p>
                {(s as any).sub && <p className="text-[10px] text-default-500">{(s as any).sub}</p>}
              </div>
            ))}
          </div>

          {/* Store profile */}
          {data.store_info?.name && (
            <Section title="ملف المتجر (من سلة)">
              <div className="flex items-center gap-2.5 mb-2.5">
                {data.store_info.avatar && (
                  <img src={data.store_info.avatar} alt="" className="w-10 h-10 rounded-xl object-cover border border-divider flex-shrink-0"
                    onError={e => { (e.currentTarget as HTMLImageElement).style.display='none' }} />
                )}
                <div className="min-w-0">
                  <p className="text-sm font-bold text-foreground truncate">{data.store_info.name}</p>
                  {data.store_info.description && (
                    <p className="text-[10px] text-default-400 leading-relaxed line-clamp-2 mt-0.5">{data.store_info.description}</p>
                  )}
                </div>
              </div>
              <div className="flex flex-wrap gap-1 mb-2">
                {data.store_info.entity && (
                  <span className="text-[10px] px-2 py-0.5 rounded bg-content2 border border-divider text-default-400">
                    {data.store_info.entity === 'company' ? 'شركة' : data.store_info.entity === 'person' ? 'فردي' : data.store_info.entity}
                  </span>
                )}
                {data.store_info.plan && (
                  <span className="text-[10px] px-2 py-0.5 rounded bg-primary/10 border border-primary/20 text-primary">
                    خطة {data.store_info.plan}
                  </span>
                )}
                {data.store_info.currency && (
                  <span className="text-[10px] px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-400">
                    {data.store_info.currency}
                  </span>
                )}
              </div>
              {(data.store_info.domain || data.store_info.email) && (
                <div className="text-[10px] text-default-500 space-y-0.5 mb-2">
                  {data.store_info.domain && <p>🌐 {data.store_info.domain}</p>}
                  {data.store_info.email  && <p>📧 {data.store_info.email}</p>}
                </div>
              )}
              {/* Social links */}
              {data.store_info.social && (
                <div className="flex flex-wrap gap-1">
                  {([
                    ['twitter','🐦 X'],['instagram','📷 IG'],['facebook','📘 FB'],
                    ['snapchat','👻 Snap'],['youtube','▶️ YT'],['telegram','✈️ TG'],
                    ['appstore_link','🍎 iOS'],['googleplay_link','🤖 Play'],
                  ] as [string,string][]).filter(([k]) =>
                    data.store_info!.social![k as keyof typeof data.store_info.social] &&
                    !['https://','http://'].includes(String(data.store_info!.social![k as keyof typeof data.store_info.social]))
                  ).map(([k,label]) => (
                    <span key={k} className="text-[10px] px-2 py-0.5 rounded bg-content2 border border-divider text-default-400">{label}</span>
                  ))}
                </div>
              )}
            </Section>
          )}

          {/* Payment methods */}
          {(data.payment_methods?.length ?? 0) > 0 && (
            <Section title="💳 طرق الدفع" count={data.payment_methods!.length}>
              <Tags items={data.payment_methods!.map(p => p.name)} />
            </Section>
          )}

          {/* Branches */}
          {(data.branches?.length ?? 0) > 0 && (
            <Section title="🏬 الفروع" count={data.branches!.length}>
              <Tags items={data.branches!.map(b => {
                const city = typeof b.city === 'object' && b.city !== null
                  ? ((b.city as {name?:string}).name || '') : (b.city || '')
                return city ? `${b.name} (${city})` : b.name
              })} />
            </Section>
          )}

          {/* Shipping */}
          {(data.shipping_companies?.length ?? 0) > 0 && (
            <Section title="🚚 شركات الشحن" count={data.shipping_companies!.length}>
              <Tags items={data.shipping_companies!.map(c =>
                `${c.activation_type === 'api' ? '🔗' : '📝'} ${c.name}`
              )} />
            </Section>
          )}

          {/* Brands */}
          {(data.brands?.length ?? 0) > 0 && (
            <Section title="🏷️ الماركات" count={data.brands!.length}>
              <Tags items={data.brands!.slice(0, 20).map(b => b.name)} />
            </Section>
          )}

          {/* Offers */}
          {(data.special_offers?.length ?? 0) > 0 && (
            <Section title="🎁 العروض الحالية" count={data.special_offers!.length}>
              <Tags items={data.special_offers!.slice(0, 10).map(o => o.message ? `${o.name} — ${o.message}` : o.name)}
                color="text-rose-400 bg-rose-500/8 border-rose-500/20" />
            </Section>
          )}

          {/* Top categories */}
          {ov.top_categories.length > 0 && (
            <Section title="📊 أكبر التصنيفات">
              <div className="space-y-1.5">
                {ov.top_categories.slice(0, 8).map(c => (
                  <div key={c.name} className="flex items-center justify-between">
                    <span className="text-xs text-default-300 truncate ml-2">{c.name}</span>
                    <span className="text-[10px] text-default-500 flex-shrink-0">{c.count}</span>
                  </div>
                ))}
              </div>
            </Section>
          )}
        </div>

        {/* Divider */}
        <div className="w-px bg-divider flex-shrink-0 mx-1" />

        {/* ══ RIGHT: Knowledge editor ══ */}
        <div className="flex-1 flex flex-col gap-4 overflow-y-auto pr-4 pl-1">

          {/* Memory usage bar */}
          <div className="flex items-center gap-3">
            <div className="flex-1 h-1.5 bg-content2 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  usedPct > 90 ? 'bg-rose-500' : usedPct > 70 ? 'bg-amber-500' : 'bg-emerald-500'
                }`}
                style={{ width: `${usedPct}%` }} />
            </div>
            <span className="text-[11px] text-default-400 whitespace-nowrap flex-shrink-0">
              {data.knowledge_chars.toLocaleString()} / {data.knowledge_budget.toLocaleString()} حرف
            </span>
          </div>

          {/* Custom knowledge textarea */}
          <div className="flex-1 flex flex-col gap-2 min-h-0">
            <div className="flex items-center justify-between">
              <label className="text-xs font-bold text-default-400 uppercase tracking-wider">
                معلومات مخصصة (تكتبها أنت — البوت يحفظها)
              </label>
              <span className="text-[10px] text-default-500">{customText.length.toLocaleString()} / 3,000</span>
            </div>
            <Textarea
              value={customText}
              onValueChange={setCustomText}
              placeholder={PLACEHOLDER}
              variant="bordered"
              minRows={12}
              maxRows={30}
              classNames={{
                base: 'flex-1',
                inputWrapper: 'border-divider bg-content2 hover:border-default-400 group-data-[focus=true]:!border-primary rounded-xl h-full',
                input: 'text-sm leading-relaxed',
              }}
            />
            <div className="flex items-center justify-between gap-3">
              <p className="text-[11px] text-default-500 leading-relaxed flex-1">
                💡 أوقات العمل، سياسات الإرجاع، معلومات الشحن، خصومات خاصة — البوت سيراها قبل كل رد.
              </p>
              <Button color="primary" isLoading={saving} onPress={save}
                isDisabled={customText.length > 3000}
                className="font-bold h-10 bg-gradient-to-r from-blue-600 to-indigo-600 flex-shrink-0">
                {saving ? '' : 'حفظ الذاكرة'}
              </Button>
            </div>
          </div>

          {/* Knowledge preview — collapsible */}
          <div className="border border-divider rounded-xl overflow-hidden flex-shrink-0">
            <button
              onClick={() => setShowPreview(p => !p)}
              className="w-full flex items-center justify-between px-4 py-3 bg-content2/60 hover:bg-content2 transition-colors text-xs font-bold text-default-400">
              <span className="flex items-center gap-2">
                <Icon d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z M12 9a3 3 0 100 6 3 3 0 000-6z" size={12} />
                ما يراه البوت فعلاً (Preview كامل)
              </span>
              <Icon d={showPreview ? 'M18 15l-6-6-6 6' : 'M6 9l6 6 6-6'} size={12} />
            </button>
            {showPreview && (
              <div className="border-t border-divider">
                <pre className="text-[11px] text-default-400 bg-content2 p-4 overflow-x-auto leading-relaxed whitespace-pre-wrap font-mono max-h-72 overflow-y-auto">
                  {data.knowledge_preview || '(لا توجد معلومات بعد — اضغط "ذاكر المتجر" لتحميل المنتجات)'}
                </pre>
              </div>
            )}
          </div>

          {/* Tips — compact */}
          <div className="bg-blue-500/5 border border-blue-500/15 rounded-xl px-4 py-3 flex-shrink-0">
            <p className="text-xs font-bold text-blue-300 mb-2">💡 نصائح سريعة</p>
            <ul className="text-[11px] text-default-500 space-y-1 leading-relaxed">
              <li>• استخدم نقاط قصيرة — أوضح للبوت من الفقرات الطويلة</li>
              <li>• غيّرت منتجاتك؟ اضغط "ذاكر المتجر" لتحديث الذاكرة</li>
              <li>• الذاكرة محفوظة في DB وتبقى بعد كل restart</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}
