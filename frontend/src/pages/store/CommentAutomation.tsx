import { useEffect, useState } from 'react'
import { Switch, Select, SelectItem, Slider, Button, Textarea, Input, Spinner, Chip } from '@heroui/react'
import { api, getEmployee } from '../../api'
import { PageHeader, SectionCard, SectionTitle, Field, InlineAlert, StatusPill } from '../../components/ui'

interface Props { storeId: string }

interface Settings {
  comments_enabled: boolean            // entitlement (read-only here)
  comments_monthly_limit: number
  comments_fb_enabled: boolean
  comments_ig_enabled: boolean
  comment_mode: 'auto' | 'approval' | 'suggest'
  comment_confidence_threshold: number
  comment_personality: { preset?: string; custom_prompt?: string }
  comment_forbidden_topics: string[]
  comment_spam_action: 'hide' | 'flag'
  page_connected: boolean
  ig_connected: boolean
}

interface Rule {
  id: number
  priority: number
  match_type: 'keyword' | 'regex' | 'intent'
  pattern: string
  action: string
  template: string
  enabled: boolean
}

const PRESETS = [
  ['friendly', 'ودود'], ['professional', 'احترافي'], ['luxury', 'فاخر'],
  ['medical', 'طبي'], ['real_estate', 'عقاري'], ['ecommerce', 'تجارة إلكترونية'],
  ['automotive', 'سيارات'],
]

export default function CommentAutomation({ storeId }: Props) {
  const role = getEmployee()?.role || 'owner'
  const canManage = role === 'owner' || role === 'manager'

  const [s, setS] = useState<Settings | null>(null)
  const [rules, setRules] = useState<Rule[]>([])
  const [msg, setMsg] = useState('')
  const [saving, setSaving] = useState(false)
  const [topicsText, setTopicsText] = useState('')

  // New-rule form
  const [nr, setNr] = useState({ match_type: 'keyword', pattern: '', action: 'reply_template', template: '', priority: 100 })

  async function load() {
    const data = await api.get<Settings>(`/admin/${storeId}/comments/settings`)
    setS(data)
    setTopicsText((data.comment_forbidden_topics || []).join('\n'))
    const r = await api.get<{ rules: Rule[] }>(`/admin/${storeId}/comments/rules`)
    setRules(r.rules)
  }

  useEffect(() => { load().catch(e => setMsg(e.message)) }, [storeId])

  async function save() {
    if (!s) return
    setSaving(true); setMsg('')
    try {
      const topics = topicsText.split('\n').map(t => t.trim()).filter(Boolean)
      const body = {
        comments_fb_enabled: s.comments_fb_enabled,
        comments_ig_enabled: s.comments_ig_enabled,
        comment_mode: s.comment_mode,
        comment_confidence_threshold: s.comment_confidence_threshold,
        comment_personality: s.comment_personality,
        comment_forbidden_topics: topics,
        comment_spam_action: s.comment_spam_action,
      }
      const updated = await api.put<Settings>(`/admin/${storeId}/comments/settings`, body)
      setS(updated)
      setMsg('تم الحفظ ✅')
    } catch (e) { setMsg((e as Error).message) }
    finally { setSaving(false) }
  }

  async function addRule() {
    if (!nr.pattern.trim()) return
    try {
      await api.post(`/admin/${storeId}/comments/rules`, nr)
      setNr({ match_type: 'keyword', pattern: '', action: 'reply_template', template: '', priority: 100 })
      const r = await api.get<{ rules: Rule[] }>(`/admin/${storeId}/comments/rules`)
      setRules(r.rules)
    } catch (e) { setMsg((e as Error).message) }
  }

  async function delRule(id: number) {
    await api.del(`/admin/${storeId}/comments/rules/${id}`)
  }

  if (!s) return <div className="flex justify-center p-12"><Spinner color="primary" label="جاري التحميل..." /></div>

  return (
    <div className="space-y-6" dir="rtl">
      <PageHeader title="أتمتة التعليقات" subtitle="ردود ذكية تلقائية على تعليقات فيسبوك وإنستقرام"
        icon={['M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-4 4z']} />

      {!s.comments_enabled && (
        <InlineAlert text="ميزة أتمتة التعليقات غير مفعّلة لهذا المتجر. تواصل مع الدعم لتفعيلها." />
      )}
      {msg && <InlineAlert text={msg} />}

      <SectionCard>
        <SectionTitle icon={['M11 5.882V19.24a1.76 1.76 0 01-3.417.592l-2.147-6.15M18 13a3 3 0 100-6']} title="القنوات" description="فعّل الردود التلقائية لكل منصة" />
        <div className="space-y-3 mt-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="font-medium">فيسبوك</div>
              <StatusPill tone={s.page_connected ? 'success' : 'default'}
                label={s.page_connected ? 'الصفحة مربوطة' : 'غير مربوطة'} />
            </div>
            <Switch isSelected={s.comments_fb_enabled} isDisabled={!canManage || !s.page_connected}
              onValueChange={v => setS({ ...s, comments_fb_enabled: v })} />
          </div>
          <div className="flex items-center justify-between">
            <div>
              <div className="font-medium">إنستقرام</div>
              <StatusPill tone={s.ig_connected ? 'success' : 'default'}
                label={s.ig_connected ? 'الحساب مربوط' : 'غير مربوط'} />
            </div>
            <Switch isSelected={s.comments_ig_enabled} isDisabled={!canManage || !s.ig_connected}
              onValueChange={v => setS({ ...s, comments_ig_enabled: v })} />
          </div>
        </div>
      </SectionCard>

      <SectionCard>
        <SectionTitle icon={['M13 10V3L4 14h7v7l9-11h-7z']} title="سلوك الرد" description="كيف يتصرف الذكاء الاصطناعي مع كل تعليق" />
        <div className="grid md:grid-cols-2 gap-4 mt-3">
          <Field label="وضع الرد">
            <Select selectedKeys={[s.comment_mode]} isDisabled={!canManage}
              onSelectionChange={k => setS({ ...s, comment_mode: Array.from(k)[0] as Settings['comment_mode'] })}>
              <SelectItem key="auto">تلقائي بالكامل</SelectItem>
              <SelectItem key="approval">يتطلب موافقة</SelectItem>
              <SelectItem key="suggest">اقتراح فقط</SelectItem>
            </Select>
          </Field>
          <Field label="إجراء السبام">
            <Select selectedKeys={[s.comment_spam_action]} isDisabled={!canManage}
              onSelectionChange={k => setS({ ...s, comment_spam_action: Array.from(k)[0] as Settings['comment_spam_action'] })}>
              <SelectItem key="flag">تمييز للمراجعة</SelectItem>
              <SelectItem key="hide">إخفاء تلقائي</SelectItem>
            </Select>
          </Field>
        </div>
        <div className="mt-4">
          <Field label={`حد الثقة للرد التلقائي: ${Math.round(s.comment_confidence_threshold * 100)}%`}
            hint="الردود التلقائية تُنشر فقط عندما تتجاوز ثقة الذكاء هذا الحد؛ ما دونه يذهب للمراجعة.">
            <Slider minValue={0} maxValue={1} step={0.05} isDisabled={!canManage}
              value={s.comment_confidence_threshold}
              onChange={v => setS({ ...s, comment_confidence_threshold: Array.isArray(v) ? v[0] : v })} />
          </Field>
        </div>
      </SectionCard>

      <SectionCard>
        <SectionTitle icon={['M16 7a4 4 0 11-8 0 4 4 0 018 0z', 'M12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z']} title="شخصية البوت" description="نبرة وأسلوب الردود" />
        <div className="grid md:grid-cols-2 gap-4 mt-3">
          <Field label="النبرة الجاهزة">
            <Select selectedKeys={[s.comment_personality?.preset || 'friendly']} isDisabled={!canManage}
              onSelectionChange={k => setS({ ...s, comment_personality: { ...s.comment_personality, preset: Array.from(k)[0] as string } })}>
              {PRESETS.map(([v, l]) => <SelectItem key={v}>{l}</SelectItem>)}
            </Select>
          </Field>
        </div>
        <div className="mt-3">
          <Field label="توجيه مخصّص (اختياري)" hint="إن كتبت توجيهاً مخصصاً فسيتجاوز النبرة الجاهزة.">
            <Textarea minRows={2} isDisabled={!canManage} value={s.comment_personality?.custom_prompt || ''}
              onValueChange={v => setS({ ...s, comment_personality: { ...s.comment_personality, custom_prompt: v } })} />
          </Field>
        </div>
      </SectionCard>

      <SectionCard>
        <SectionTitle icon={['M12 9v2m0 4h.01M5.07 19H19a2 2 0 001.74-3L13.74 4a2 2 0 00-3.48 0L3.33 16a2 2 0 001.74 3z']} title="المواضيع المحظورة" description="تعليقات تمسّ هذه المواضيع تُصعّد لموظف ولا يُرد عليها آلياً" />
        <Textarea minRows={3} isDisabled={!canManage} className="mt-3"
          placeholder={'موضوع في كل سطر\nمثال: قضية قانونية\nمثال: ادعاء طبي'}
          value={topicsText} onValueChange={setTopicsText} />
      </SectionCard>

      {canManage && (
        <div className="flex items-center gap-3">
          <Button color="primary" isLoading={saving} onPress={save}>حفظ الإعدادات</Button>
        </div>
      )}

      <SectionCard>
        <SectionTitle icon={['M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z']} title="قواعد الرد" description="ردود محدّدة مسبقاً تُطبّق قبل الذكاء الاصطناعي" />
        <div className="space-y-2 mt-3">
          {rules.length === 0 && <div className="text-sm text-foreground-500">لا توجد قواعد بعد.</div>}
          {rules.map(r => (
            <div key={r.id} className="flex items-center justify-between gap-3 rounded-lg border border-default-200 p-3">
              <div className="flex items-center gap-2 flex-wrap">
                <Chip size="sm" variant="flat">{r.match_type}</Chip>
                <span className="font-mono text-sm">{r.pattern}</span>
                <span className="text-foreground-400">→</span>
                <Chip size="sm" color="primary" variant="flat">{r.action}</Chip>
              </div>
              {canManage && <Button size="sm" variant="light" color="danger" onPress={() => delRule(r.id).then(load)}>حذف</Button>}
            </div>
          ))}
        </div>

        {canManage && (
          <div className="grid md:grid-cols-5 gap-2 mt-4 items-end">
            <Select label="النوع" size="sm" selectedKeys={[nr.match_type]}
              onSelectionChange={k => setNr({ ...nr, match_type: Array.from(k)[0] as string })}>
              <SelectItem key="keyword">كلمة</SelectItem>
              <SelectItem key="regex">Regex</SelectItem>
              <SelectItem key="intent">نيّة</SelectItem>
            </Select>
            <Input label="النمط" size="sm" value={nr.pattern} onValueChange={v => setNr({ ...nr, pattern: v })} />
            <Select label="الإجراء" size="sm" selectedKeys={[nr.action]}
              onSelectionChange={k => setNr({ ...nr, action: Array.from(k)[0] as string })}>
              <SelectItem key="reply_template">ردّ جاهز</SelectItem>
              <SelectItem key="send_contact">إرسال تواصل</SelectItem>
              <SelectItem key="escalate">تصعيد</SelectItem>
              <SelectItem key="hide">إخفاء</SelectItem>
              <SelectItem key="ignore">تجاهل</SelectItem>
            </Select>
            <Input label="الردّ" size="sm" value={nr.template} onValueChange={v => setNr({ ...nr, template: v })} />
            <Button color="primary" size="sm" onPress={addRule}>إضافة</Button>
          </div>
        )}
      </SectionCard>
    </div>
  )
}
