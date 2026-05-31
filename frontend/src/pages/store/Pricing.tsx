import { useEffect, useState } from 'react'
import {
  Card, CardBody, CardHeader,
  Button, Input, Switch, Tabs, Tab,
  Divider, Spinner, Chip,
} from '@heroui/react'
import {
  api, PricingConfig, PaperType, SheetSize, AddonItem, DiscountRule, TierRule,
} from '../../api'

interface Props { storeId: string }

const PRINTING_TYPE_LABELS: Record<string, string> = {
  roll: 'رول', digital: 'ديجيتال', offset: 'أوفست', uvdtf: 'UV DTF',
}

function Icon({ paths, size = 14, className = '' }: { paths: string | string[]; size?: number; className?: string }) {
  const arr = Array.isArray(paths) ? paths : [paths]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={className}>
      {arr.map((d, i) => <path key={i} d={d} />)}
    </svg>
  )
}

export default function Pricing({ storeId }: Props) {
  const [cfg, setCfg] = useState<PricingConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [tab, setTab] = useState<string>('general')

  useEffect(() => { load() }, [storeId])

  async function load() {
    setLoading(true)
    try {
      const data = await api.getPricing(storeId)
      setCfg(data)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  async function save() {
    if (!cfg) return
    setSaving(true); setMsg('')
    try {
      await api.setPricing(storeId, cfg)
      setMsg('✅ تم حفظ إعدادات الحاسبة')
    } catch (e: unknown) {
      setMsg(e instanceof Error ? e.message : 'خطأ في الحفظ')
    } finally { setSaving(false) }
  }

  function patch<K extends keyof PricingConfig>(key: K, value: PricingConfig[K]) {
    setCfg(prev => prev ? { ...prev, [key]: value } : prev)
  }

  if (loading || !cfg) {
    return <div className="flex items-center justify-center min-h-[400px]"><Spinner color="primary" /></div>
  }

  const inputCls = {
    inputWrapper: 'border-divider bg-content2 h-10 min-h-10',
    label:        'text-default-400 text-xs font-medium',
    input:        'text-foreground text-sm',
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5" dir="rtl">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-foreground">حاسبة أسعار الطباعة</h1>
          <p className="text-sm text-default-500 mt-1">
            الأسعار اللي تضبطها هنا الـ AI هيستخدمها لما يحسب للعميل من الشات
          </p>
        </div>
        <Button
          color="primary" isLoading={saving} onPress={save}
          className="font-bold h-11 bg-gradient-to-r from-blue-600 to-indigo-600 shadow-lg shadow-blue-500/20"
        >
          {saving ? '' : 'حفظ الإعدادات'}
        </Button>
      </header>

      {msg && (
        <div className={`rounded-lg p-3 text-sm border ${
          msg.startsWith('✅')
            ? 'bg-success/10 border-success/20 text-success'
            : 'bg-danger/10 border-danger/20 text-danger'
        }`}>{msg}</div>
      )}

      <Tabs
        selectedKey={tab}
        onSelectionChange={(k) => setTab(String(k))}
        variant="bordered"
        classNames={{
          tabList: 'bg-content1 border border-divider p-1',
          cursor:  'bg-primary/15 border border-primary/30',
          tab:     'h-9 text-xs',
        }}
      >
        <Tab key="general" title="عام" />
        <Tab key="roll"    title="رول" />
        <Tab key="digital" title="ديجيتال" />
        <Tab key="offset"  title="أوفست" />
        <Tab key="uvdtf"   title="UV DTF" />
        <Tab key="test"    title="🧪 اختبار" />
      </Tabs>

      {/* ════════════ GENERAL ════════════ */}
      {tab === 'general' && (
        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-blue-400" />
            <h2 className="font-bold text-sm">إعدادات عامة</h2>
          </CardHeader>
          <Divider />
          <CardBody className="px-5 py-6 grid grid-cols-1 md:grid-cols-2 gap-5">
            <Input
              type="number" label="نسبة الضريبة (VAT) %"
              value={String(cfg.tax_rate)} onValueChange={v => patch('tax_rate', parseFloat(v) || 0)}
              variant="bordered" labelPlacement="outside" placeholder="15"
              description="النسبة الافتراضية في السعودية 15%"
              classNames={inputCls}
            />
            <Input
              type="number" label="هامش الربح %"
              value={String(cfg.profit_margin)} onValueChange={v => patch('profit_margin', parseFloat(v) || 0)}
              variant="bordered" labelPlacement="outside" placeholder="15"
              description="يُضاف فوق التكلفة قبل الضريبة"
              classNames={inputCls}
            />

            <div className="md:col-span-2 mt-2 space-y-3">
              <h3 className="text-sm font-bold text-default-500">تفعيل أنواع الطباعة</h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {(['roll', 'digital', 'offset', 'uvdtf'] as const).map(t => {
                  const key = `${t}_enabled` as keyof PricingConfig
                  const enabled = Boolean(cfg[key])
                  return (
                    <button
                      key={t}
                      onClick={() => patch(key, !enabled as any)}
                      className={`p-4 rounded-xl border text-center transition-colors ${
                        enabled
                          ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300'
                          : 'bg-content2 border-divider text-default-500 hover:border-slate-500'
                      }`}
                    >
                      <div className="text-sm font-bold mb-1">{PRINTING_TYPE_LABELS[t]}</div>
                      <Chip size="sm" color={enabled ? 'success' : 'default'} variant="flat">
                        {enabled ? 'مُفعّل' : 'معطّل'}
                      </Chip>
                    </button>
                  )
                })}
              </div>
            </div>
          </CardBody>
        </Card>
      )}

      {/* ════════════ ROLL ════════════ */}
      {tab === 'roll' && (
        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              <h2 className="font-bold text-sm">إعدادات الرول (Roll-to-Roll)</h2>
            </div>
            <Chip size="sm" color={cfg.roll_enabled ? 'success' : 'default'} variant="flat">
              {cfg.roll_enabled ? 'مُفعّل' : 'معطّل'}
            </Chip>
          </CardHeader>
          <Divider />
          <CardBody className="px-5 py-6 space-y-5">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <Input
                type="number" label="سعر المتر المربع الأساسي (ريال)"
                value={String(cfg.roll_unit_price)}
                onValueChange={v => patch('roll_unit_price', parseFloat(v) || 0)}
                variant="bordered" labelPlacement="outside" classNames={inputCls}
              />
              <Input
                type="number" label="عرض الرول الافتراضي (سم)"
                value={String(cfg.default_roll_width)}
                onValueChange={v => patch('default_roll_width', parseFloat(v) || 0)}
                variant="bordered" labelPlacement="outside" classNames={inputCls}
              />
            </div>
            <DiscountEditor
              title="شرائح الخصم على المساحة (متر مربع)"
              rules={cfg.roll_discounts}
              onChange={r => patch('roll_discounts', r)}
              unitLabel="م²"
            />
          </CardBody>
        </Card>
      )}

      {/* ════════════ DIGITAL ════════════ */}
      {tab === 'digital' && (
        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-violet-400" />
              <h2 className="font-bold text-sm">إعدادات الديجيتال</h2>
            </div>
            <Chip size="sm" color={cfg.digital_enabled ? 'success' : 'default'} variant="flat">
              {cfg.digital_enabled ? 'مُفعّل' : 'معطّل'}
            </Chip>
          </CardHeader>
          <Divider />
          <CardBody className="px-5 py-6 space-y-6">

            <PaperListEditor
              title="أنواع الورق"
              papers={cfg.digital_paper_types}
              onChange={p => patch('digital_paper_types', p)}
              priceLabel="السعر/شيت (ريال)"
            />

            <div className="space-y-2">
              <h3 className="text-sm font-bold text-default-500">مقاسات الورق</h3>
              <SheetSizeEditor
                sizes={cfg.digital_sheet_sizes}
                onChange={s => patch('digital_sheet_sizes', s)}
              />
            </div>

            <AddonListEditor
              addons={cfg.digital_addons}
              onChange={a => patch('digital_addons', a)}
            />

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 bg-violet-500/5 p-4 rounded-xl border border-violet-500/20">
              <h3 className="md:col-span-3 text-sm font-bold text-violet-300">إعدادات البصمة (Foil)</h3>
              <Input
                type="number" label="سعر 1 سم² للقالب"
                value={String(cfg.foil_mold_price_per_cm2)}
                onValueChange={v => patch('foil_mold_price_per_cm2', parseFloat(v) || 0)}
                variant="bordered" labelPlacement="outside" classNames={inputCls}
              />
              <Input
                type="number" label="الحد الأدنى لسعر القالب"
                value={String(cfg.foil_min_mold_price)}
                onValueChange={v => patch('foil_min_mold_price', parseFloat(v) || 0)}
                variant="bordered" labelPlacement="outside" classNames={inputCls}
              />
              <Input
                type="number" label="سعر التبصيم (للحبة)"
                value={String(cfg.foil_stamping_unit_price)}
                onValueChange={v => patch('foil_stamping_unit_price', parseFloat(v) || 0)}
                variant="bordered" labelPlacement="outside" classNames={inputCls}
              />
            </div>

            <DiscountEditor
              title="شرائح الخصم على عدد الشيتات"
              rules={cfg.digital_discounts}
              onChange={r => patch('digital_discounts', r)}
              unitLabel="شيت"
            />
          </CardBody>
        </Card>
      )}

      {/* ════════════ OFFSET ════════════ */}
      {tab === 'offset' && (
        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-amber-400" />
              <h2 className="font-bold text-sm">إعدادات الأوفست</h2>
            </div>
            <Chip size="sm" color={cfg.offset_enabled ? 'success' : 'default'} variant="flat">
              {cfg.offset_enabled ? 'مُفعّل' : 'معطّل'}
            </Chip>
          </CardHeader>
          <Divider />
          <CardBody className="px-5 py-6 space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <Input
                type="number" label="ثابت العرض (A)"
                value={String(cfg.offset_fixed_width)}
                onValueChange={v => patch('offset_fixed_width', parseFloat(v) || 0)}
                variant="bordered" labelPlacement="outside" classNames={inputCls}
                description="يُستخدم في معادلة CEILING(عرض ÷ A)"
              />
              <Input
                type="number" label="ثابت الطول (B)"
                value={String(cfg.offset_fixed_height)}
                onValueChange={v => patch('offset_fixed_height', parseFloat(v) || 0)}
                variant="bordered" labelPlacement="outside" classNames={inputCls}
                description="يُستخدم في معادلة CEILING(طول ÷ B)"
              />
            </div>

            <PaperListEditor
              title="أنواع ورق الأوفست (السعر لكل 1000)"
              papers={cfg.offset_paper_types}
              onChange={p => patch('offset_paper_types', p)}
              priceLabel="السعر/1000 (ريال)"
            />

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 bg-amber-500/5 p-4 rounded-xl border border-amber-500/20">
              <h3 className="col-span-2 md:col-span-4 text-sm font-bold text-amber-300">تكاليف إضافية (لكل 1000)</h3>
              <Input
                type="number" label="قص عادي"
                value={String(cfg.offset_cutting_normal)}
                onValueChange={v => patch('offset_cutting_normal', parseFloat(v) || 0)}
                variant="bordered" labelPlacement="outside" classNames={inputCls}
              />
              <Input
                type="number" label="قص داي كت"
                value={String(cfg.offset_cutting_diecut)}
                onValueChange={v => patch('offset_cutting_diecut', parseFloat(v) || 0)}
                variant="bordered" labelPlacement="outside" classNames={inputCls}
              />
              <Input
                type="number" label="ثنية"
                value={String(cfg.offset_folding_per_1000)}
                onValueChange={v => patch('offset_folding_per_1000', parseFloat(v) || 0)}
                variant="bordered" labelPlacement="outside" classNames={inputCls}
              />
              <Input
                type="number" label="تخريم"
                value={String(cfg.offset_punching_per_1000)}
                onValueChange={v => patch('offset_punching_per_1000', parseFloat(v) || 0)}
                variant="bordered" labelPlacement="outside" classNames={inputCls}
              />
            </div>

            <DiscountEditor
              title="شرائح الخصم على الكمية"
              rules={cfg.offset_discounts}
              onChange={r => patch('offset_discounts', r)}
              unitLabel="قطعة"
            />
          </CardBody>
        </Card>
      )}

      {/* ════════════ UV DTF ════════════ */}
      {tab === 'uvdtf' && (
        <Card className="bg-content1 border border-divider">
          <CardHeader className="px-5 py-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-pink-400" />
              <h2 className="font-bold text-sm">إعدادات UV DTF</h2>
            </div>
            <Chip size="sm" color={cfg.uvdtf_enabled ? 'success' : 'default'} variant="flat">
              {cfg.uvdtf_enabled ? 'مُفعّل' : 'معطّل'}
            </Chip>
          </CardHeader>
          <Divider />
          <CardBody className="px-5 py-6 space-y-5">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <Input
                type="number" label="سعر المتر الطولي الأساسي (ريال)"
                value={String(cfg.uvdtf_unit_price)}
                onValueChange={v => patch('uvdtf_unit_price', parseFloat(v) || 0)}
                variant="bordered" labelPlacement="outside" classNames={inputCls}
              />
              <Input
                type="number" label="عرض المسطح الفعلي (سم)"
                value={String(cfg.uvdtf_roll_width)}
                onValueChange={v => patch('uvdtf_roll_width', parseFloat(v) || 0)}
                variant="bordered" labelPlacement="outside" classNames={inputCls}
              />
            </div>
            <TierEditor
              title="شرائح السعر حسب الاستهلاك (متر طولي)"
              tiers={cfg.uvdtf_tiers}
              onChange={t => patch('uvdtf_tiers', t)}
              unitLabel="متر"
              priceLabel="سعر المتر"
            />
          </CardBody>
        </Card>
      )}

      {/* ════════════ TEST ════════════ */}
      {tab === 'test' && <TestCalculator storeId={storeId} cfg={cfg} />}
    </div>
  )
}

// ── Discount / Tier editors ────────────────────────────────────────────────

function DiscountEditor({ title, rules, onChange, unitLabel }: {
  title: string; rules: DiscountRule[]; onChange: (r: DiscountRule[]) => void; unitLabel: string
}) {
  const [min, setMin] = useState(''); const [pct, setPct] = useState('')
  function add() {
    const m = parseFloat(min); const p = parseFloat(pct)
    if (!isFinite(m) || !isFinite(p)) return
    onChange([...rules, { min: m, percent: p }].sort((a, b) => a.min - b.min))
    setMin(''); setPct('')
  }
  return (
    <div className="bg-content2 rounded-xl border border-divider p-4">
      <h3 className="text-sm font-bold text-default-500 mb-3">{title}</h3>
      <div className="space-y-1.5 mb-3">
        {rules.length === 0 && <p className="text-xs text-default-500 text-center py-2">لا توجد شرائح خصم</p>}
        {rules.map((r, i) => (
          <div key={i} className="flex items-center justify-between bg-content1 px-3 py-2 rounded-lg text-xs">
            <span>من <b className="text-blue-400">{r.min}</b> {unitLabel} فأكثر</span>
            <div className="flex items-center gap-2">
              <Chip size="sm" color="warning" variant="flat">خصم {r.percent}%</Chip>
              <button onClick={() => onChange(rules.filter((_, idx) => idx !== i))} className="text-default-400 hover:text-danger">
                <Icon paths={['M19 7L18.1 19.2A2 2 0 0116.1 21H7.9A2 2 0 015.9 19.2L5 7', 'M10 11v6', 'M14 11v6', 'M3 7h18', 'M8 7V4a1 1 0 011-1h6a1 1 0 011 1v3']} />
              </button>
            </div>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <Input size="sm" placeholder={`الحد الأدنى (${unitLabel})`} type="number" value={min} onValueChange={setMin}
               variant="bordered" classNames={{ inputWrapper: 'border-divider bg-content1' }} />
        <Input size="sm" placeholder="نسبة الخصم %" type="number" value={pct} onValueChange={setPct}
               variant="bordered" classNames={{ inputWrapper: 'border-divider bg-content1' }} />
        <Button size="sm" color="primary" onPress={add} isIconOnly><Icon paths="M12 5v14M5 12h14" /></Button>
      </div>
    </div>
  )
}

function TierEditor({ title, tiers, onChange, unitLabel, priceLabel }: {
  title: string; tiers: TierRule[]; onChange: (t: TierRule[]) => void; unitLabel: string; priceLabel: string
}) {
  const [min, setMin] = useState(''); const [price, setPrice] = useState('')
  function add() {
    const m = parseFloat(min); const p = parseFloat(price)
    if (!isFinite(m) || !isFinite(p)) return
    onChange([...tiers, { min: m, price: p }].sort((a, b) => a.min - b.min))
    setMin(''); setPrice('')
  }
  return (
    <div className="bg-content2 rounded-xl border border-divider p-4">
      <h3 className="text-sm font-bold text-default-500 mb-3">{title}</h3>
      <div className="space-y-1.5 mb-3">
        {tiers.length === 0 && <p className="text-xs text-default-500 text-center py-2">لا توجد شرائح أسعار</p>}
        {tiers.map((t, i) => (
          <div key={i} className="flex items-center justify-between bg-content1 px-3 py-2 rounded-lg text-xs">
            <span>من <b className="text-blue-400">{t.min}</b> {unitLabel} فأكثر</span>
            <div className="flex items-center gap-2">
              <Chip size="sm" color="primary" variant="flat">{t.price} ريال</Chip>
              <button onClick={() => onChange(tiers.filter((_, idx) => idx !== i))} className="text-default-400 hover:text-danger">
                <Icon paths={['M19 7L18.1 19.2A2 2 0 0116.1 21H7.9A2 2 0 015.9 19.2L5 7', 'M10 11v6', 'M14 11v6', 'M3 7h18', 'M8 7V4a1 1 0 011-1h6a1 1 0 011 1v3']} />
              </button>
            </div>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <Input size="sm" placeholder={`الحد الأدنى (${unitLabel})`} type="number" value={min} onValueChange={setMin}
               variant="bordered" classNames={{ inputWrapper: 'border-divider bg-content1' }} />
        <Input size="sm" placeholder={priceLabel} type="number" value={price} onValueChange={setPrice}
               variant="bordered" classNames={{ inputWrapper: 'border-divider bg-content1' }} />
        <Button size="sm" color="primary" onPress={add} isIconOnly><Icon paths="M12 5v14M5 12h14" /></Button>
      </div>
    </div>
  )
}

// ── Paper / Sheet / Addon list editors ─────────────────────────────────────

function PaperListEditor({ title, papers, onChange, priceLabel }: {
  title: string; papers: PaperType[]; onChange: (p: PaperType[]) => void; priceLabel: string
}) {
  const [name, setName] = useState(''); const [price, setPrice] = useState('')
  function add() {
    if (!name.trim()) return
    onChange([...papers, { name: name.trim(), price: parseFloat(price) || 0, active: true }])
    setName(''); setPrice('')
  }
  return (
    <div className="bg-content2 rounded-xl border border-divider p-4">
      <h3 className="text-sm font-bold text-default-500 mb-3">{title}</h3>
      <div className="space-y-1.5 mb-3">
        {papers.length === 0 && <p className="text-xs text-default-500 text-center py-2">لا توجد أنواع ورق مضافة</p>}
        {papers.map((p, i) => (
          <div key={i} className={`flex items-center gap-2 bg-content1 px-3 py-2 rounded-lg ${p.active === false ? 'opacity-50' : ''}`}>
            <Switch
              size="sm" isSelected={p.active !== false}
              onValueChange={v => onChange(papers.map((x, idx) => idx === i ? { ...x, active: v } : x))}
            />
            <Input size="sm" value={p.name}
                   onValueChange={v => onChange(papers.map((x, idx) => idx === i ? { ...x, name: v } : x))}
                   variant="flat" classNames={{ inputWrapper: 'bg-transparent shadow-none h-7 min-h-7', input: 'text-xs font-bold' }}
                   className="flex-1" />
            <Input size="sm" type="number" value={String(p.price)}
                   onValueChange={v => onChange(papers.map((x, idx) => idx === i ? { ...x, price: parseFloat(v) || 0 } : x))}
                   variant="bordered" classNames={{ inputWrapper: 'border-divider h-7 min-h-7', input: 'text-xs text-center' }}
                   className="w-20" />
            <button onClick={() => onChange(papers.filter((_, idx) => idx !== i))} className="text-default-400 hover:text-danger">
              <Icon paths={['M19 7L18.1 19.2A2 2 0 0116.1 21H7.9A2 2 0 015.9 19.2L5 7', 'M10 11v6', 'M14 11v6', 'M3 7h18', 'M8 7V4a1 1 0 011-1h6a1 1 0 011 1v3']} />
            </button>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <Input size="sm" placeholder="اسم الورق (مثل: كوشيه 300)" value={name} onValueChange={setName}
               variant="bordered" classNames={{ inputWrapper: 'border-divider bg-content1' }} />
        <Input size="sm" placeholder={priceLabel} type="number" value={price} onValueChange={setPrice}
               variant="bordered" classNames={{ inputWrapper: 'border-divider bg-content1' }} />
        <Button size="sm" color="primary" onPress={add} isIconOnly><Icon paths="M12 5v14M5 12h14" /></Button>
      </div>
    </div>
  )
}

function SheetSizeEditor({ sizes, onChange }: { sizes: SheetSize[]; onChange: (s: SheetSize[]) => void }) {
  const [name, setName] = useState(''); const [w, setW] = useState(''); const [h, setH] = useState('')
  function add() {
    if (!name.trim()) return
    onChange([...sizes, { name: name.trim(), width: parseFloat(w) || 0, height: parseFloat(h) || 0 }])
    setName(''); setW(''); setH('')
  }
  return (
    <div className="bg-content2 rounded-xl border border-divider p-4">
      <div className="space-y-1.5 mb-3">
        {sizes.map((s, i) => (
          <div key={i} className="flex items-center gap-2 bg-content1 px-3 py-2 rounded-lg">
            <Input size="sm" value={s.name}
                   onValueChange={v => onChange(sizes.map((x, idx) => idx === i ? { ...x, name: v } : x))}
                   variant="flat" classNames={{ inputWrapper: 'bg-transparent shadow-none h-7 min-h-7', input: 'text-xs font-bold' }}
                   className="flex-1" />
            <Input size="sm" type="number" value={String(s.width)}
                   onValueChange={v => onChange(sizes.map((x, idx) => idx === i ? { ...x, width: parseFloat(v) || 0 } : x))}
                   variant="bordered" classNames={{ inputWrapper: 'border-divider h-7 min-h-7', input: 'text-xs text-center' }}
                   className="w-16" />
            <span className="text-xs text-default-400">×</span>
            <Input size="sm" type="number" value={String(s.height)}
                   onValueChange={v => onChange(sizes.map((x, idx) => idx === i ? { ...x, height: parseFloat(v) || 0 } : x))}
                   variant="bordered" classNames={{ inputWrapper: 'border-divider h-7 min-h-7', input: 'text-xs text-center' }}
                   className="w-16" />
            <span className="text-[10px] text-default-500">سم</span>
            <button onClick={() => onChange(sizes.filter((_, idx) => idx !== i))} className="text-default-400 hover:text-danger">
              <Icon paths={['M19 7L18.1 19.2A2 2 0 0116.1 21H7.9A2 2 0 015.9 19.2L5 7', 'M10 11v6', 'M14 11v6', 'M3 7h18', 'M8 7V4a1 1 0 011-1h6a1 1 0 011 1v3']} />
            </button>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <Input size="sm" placeholder="اسم المقاس" value={name} onValueChange={setName}
               variant="bordered" classNames={{ inputWrapper: 'border-divider bg-content1' }} />
        <Input size="sm" placeholder="عرض" type="number" value={w} onValueChange={setW}
               variant="bordered" classNames={{ inputWrapper: 'border-divider bg-content1' }} className="w-20" />
        <Input size="sm" placeholder="طول" type="number" value={h} onValueChange={setH}
               variant="bordered" classNames={{ inputWrapper: 'border-divider bg-content1' }} className="w-20" />
        <Button size="sm" color="primary" onPress={add} isIconOnly><Icon paths="M12 5v14M5 12h14" /></Button>
      </div>
    </div>
  )
}

function AddonListEditor({ addons, onChange }: { addons: AddonItem[]; onChange: (a: AddonItem[]) => void }) {
  const [name, setName] = useState(''); const [price, setPrice] = useState('')
  function add() {
    if (!name.trim()) return
    onChange([...addons, { name: name.trim(), price: parseFloat(price) || 0 }])
    setName(''); setPrice('')
  }
  return (
    <div className="bg-content2 rounded-xl border border-divider p-4">
      <h3 className="text-sm font-bold text-default-500 mb-3">إضافات الديجيتال (سلوفان، لمنيشن، إلخ)</h3>
      <div className="space-y-1.5 mb-3">
        {addons.length === 0 && <p className="text-xs text-default-500 text-center py-2">لا توجد إضافات</p>}
        {addons.map((a, i) => (
          <div key={i} className="flex items-center gap-2 bg-content1 px-3 py-2 rounded-lg">
            <Input size="sm" value={a.name}
                   onValueChange={v => onChange(addons.map((x, idx) => idx === i ? { ...x, name: v } : x))}
                   variant="flat" classNames={{ inputWrapper: 'bg-transparent shadow-none h-7 min-h-7', input: 'text-xs font-bold' }}
                   className="flex-1" />
            <Input size="sm" type="number" value={String(a.price)}
                   onValueChange={v => onChange(addons.map((x, idx) => idx === i ? { ...x, price: parseFloat(v) || 0 } : x))}
                   variant="bordered" classNames={{ inputWrapper: 'border-divider h-7 min-h-7', input: 'text-xs text-center' }}
                   className="w-20" />
            <span className="text-[10px] text-default-500">ريال/شيت</span>
            <button onClick={() => onChange(addons.filter((_, idx) => idx !== i))} className="text-default-400 hover:text-danger">
              <Icon paths={['M19 7L18.1 19.2A2 2 0 0116.1 21H7.9A2 2 0 015.9 19.2L5 7', 'M10 11v6', 'M14 11v6', 'M3 7h18', 'M8 7V4a1 1 0 011-1h6a1 1 0 011 1v3']} />
            </button>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <Input size="sm" placeholder="اسم الإضافة" value={name} onValueChange={setName}
               variant="bordered" classNames={{ inputWrapper: 'border-divider bg-content1' }} />
        <Input size="sm" placeholder="السعر/شيت" type="number" value={price} onValueChange={setPrice}
               variant="bordered" classNames={{ inputWrapper: 'border-divider bg-content1' }} className="w-24" />
        <Button size="sm" color="primary" onPress={add} isIconOnly><Icon paths="M12 5v14M5 12h14" /></Button>
      </div>
    </div>
  )
}

// ── Test calculator preview ────────────────────────────────────────────────

function TestCalculator({ storeId, cfg }: { storeId: string; cfg: PricingConfig }) {
  const [printingType, setPrintingType] = useState<'roll' | 'digital' | 'offset' | 'uvdtf'>('digital')
  const [width, setWidth] = useState('9')
  const [height, setHeight] = useState('5')
  const [quantity, setQuantity] = useState('1000')
  const [paperType, setPaperType] = useState<string>('')
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [running, setRunning] = useState(false)

  async function run() {
    setRunning(true)
    try {
      const r = await api.testPricing(storeId, {
        printing_type: printingType,
        width: parseFloat(width) || 0,
        height: parseFloat(height) || 0,
        quantity: parseInt(quantity) || 0,
        paper_type: paperType || undefined,
      })
      setResult(r)
    } catch (e) {
      setResult({ error: e instanceof Error ? e.message : 'خطأ' })
    } finally { setRunning(false) }
  }

  const papers = printingType === 'digital'
    ? cfg.digital_paper_types.filter(p => p.active !== false)
    : printingType === 'offset'
    ? cfg.offset_paper_types.filter(p => p.active !== false)
    : []

  return (
    <Card className="bg-content1 border border-divider">
      <CardHeader className="px-5 py-4 flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-cyan-400" />
        <h2 className="font-bold text-sm">اختبار الحاسبة بقيم تجريبية</h2>
      </CardHeader>
      <Divider />
      <CardBody className="px-5 py-6 space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <select
            value={printingType}
            onChange={e => setPrintingType(e.target.value as any)}
            className="bg-content2 border border-divider rounded-lg px-3 py-2 text-sm text-foreground"
          >
            <option value="roll">رول</option>
            <option value="digital">ديجيتال</option>
            <option value="offset">أوفست</option>
            <option value="uvdtf">UV DTF</option>
          </select>
          <Input size="sm" label="عرض" placeholder="9" type="number" value={width} onValueChange={setWidth}
                 variant="bordered" labelPlacement="outside"
                 classNames={{ inputWrapper: 'border-divider bg-content2' }} />
          <Input size="sm" label="ارتفاع" placeholder="5" type="number" value={height} onValueChange={setHeight}
                 variant="bordered" labelPlacement="outside"
                 classNames={{ inputWrapper: 'border-divider bg-content2' }} />
          <Input size="sm" label="كمية" placeholder="1000" type="number" value={quantity} onValueChange={setQuantity}
                 variant="bordered" labelPlacement="outside"
                 classNames={{ inputWrapper: 'border-divider bg-content2' }} />
        </div>

        {papers.length > 0 && (
          <select
            value={paperType}
            onChange={e => setPaperType(e.target.value)}
            className="w-full bg-content2 border border-divider rounded-lg px-3 py-2 text-sm text-foreground"
          >
            <option value="">— نوع ورق افتراضي —</option>
            {papers.map(p => <option key={p.name} value={p.name}>{p.name}</option>)}
          </select>
        )}

        <Button color="primary" onPress={run} isLoading={running} className="w-full font-bold">
          {running ? '' : '🧮 احسب'}
        </Button>

        {result && (
          <div className={`rounded-xl p-4 border ${
            result.error
              ? 'bg-danger/10 border-danger/20 text-danger'
              : 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300'
          }`}>
            {result.error ? (
              <p className="text-sm">{String(result.error)}</p>
            ) : (
              <div className="space-y-2">
                <div className="flex items-baseline justify-between border-b border-emerald-500/20 pb-2">
                  <span className="text-xs text-default-400">السعر النهائي</span>
                  <span className="text-2xl font-bold text-emerald-300">
                    {Number(result.final_price).toLocaleString('en-US', { maximumFractionDigits: 2 })} ريال
                  </span>
                </div>
                <pre className="text-[10px] text-default-400 bg-content2 p-3 rounded overflow-x-auto font-mono">
{JSON.stringify(result, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  )
}
