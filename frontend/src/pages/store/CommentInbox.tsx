import { useEffect, useState } from 'react'
import { Select, SelectItem, Button, Textarea, Chip, Spinner } from '@heroui/react'
import { api, getEmployee } from '../../api'
import { PageHeader, StatCard, EmptyState } from '../../components/ui'

interface Props { storeId: string }

interface Comment {
  id: number
  platform: 'facebook' | 'instagram'
  author_name: string
  message: string
  permalink: string
  sentiment: string
  intent: string
  category: string
  lead_temp: string
  lead_score: number
  ai_confidence: number | null
  status: string
  suggested_reply: string
  final_reply: string
  created_at: string
}

interface Analytics {
  total: number; replied: number; response_rate: number
  ai_response_rate: number; leads: number; avg_response_secs: number
}

const STATUS_AR: Record<string, string> = {
  new: 'جديد', ai_replied: 'ردّ آلي', pending_approval: 'بانتظار الموافقة',
  replied: 'تم الرد', assigned: 'مُسند', resolved: 'مغلق', hidden: 'مخفي', ignored: 'متجاهَل',
}
const SENT_TONE: Record<string, 'success' | 'warning' | 'danger' | 'default'> = {
  positive: 'success', neutral: 'default', negative: 'danger',
}
const LEAD_TONE: Record<string, 'danger' | 'warning' | 'default'> = {
  hot: 'danger', warm: 'warning', cold: 'default',
}

export default function CommentInbox({ storeId }: Props) {
  const role = getEmployee()?.role || 'owner'
  const canAct = role !== 'viewer'

  const [comments, setComments] = useState<Comment[]>([])
  const [stats, setStats] = useState<Analytics | null>(null)
  const [loading, setLoading] = useState(true)
  const [platform, setPlatform] = useState('')
  const [status, setStatus] = useState('')
  const [draft, setDraft] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState<number | null>(null)

  async function load() {
    setLoading(true)
    const qs = new URLSearchParams()
    if (platform) qs.set('platform', platform)
    if (status) qs.set('status', status)
    const data = await api.get<{ comments: Comment[] }>(`/admin/${storeId}/comments?${qs}`)
    setComments(data.comments)
    setStats(await api.get<Analytics>(`/admin/${storeId}/comments/analytics`))
    setLoading(false)
  }

  useEffect(() => { load().catch(() => setLoading(false)) }, [storeId, platform, status])

  async function act(id: number, path: string, body?: unknown) {
    setBusy(id)
    try {
      await api.post(`/admin/${storeId}/comments/${id}/${path}`, body)
      await load()
    } catch (e) { alert((e as Error).message) }
    finally { setBusy(null) }
  }

  const mins = (s: number) => s >= 60 ? `${Math.round(s / 60)} د` : `${s} ث`

  return (
    <div className="space-y-6" dir="rtl">
      <PageHeader title="صندوق التعليقات" subtitle="تعليقات فيسبوك وإنستقرام في مكان واحد"
        icon={['M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z']} />

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="إجمالي التعليقات" value={String(stats.total)} />
          <StatCard label="نسبة الرد" value={`${Math.round(stats.response_rate * 100)}%`} />
          <StatCard label="ردّ آلي" value={`${Math.round(stats.ai_response_rate * 100)}%`} />
          <StatCard label="عملاء محتملون" value={String(stats.leads)} />
        </div>
      )}

      <div className="flex gap-2 flex-wrap">
        <Select size="sm" className="max-w-40" label="المنصة" selectedKeys={platform ? [platform] : []}
          onSelectionChange={k => setPlatform((Array.from(k)[0] as string) || '')}>
          <SelectItem key="">الكل</SelectItem>
          <SelectItem key="facebook">فيسبوك</SelectItem>
          <SelectItem key="instagram">إنستقرام</SelectItem>
        </Select>
        <Select size="sm" className="max-w-48" label="الحالة" selectedKeys={status ? [status] : []}
          onSelectionChange={k => setStatus((Array.from(k)[0] as string) || '')}>
          <SelectItem key="">الكل</SelectItem>
          <SelectItem key="pending_approval">بانتظار الموافقة</SelectItem>
          <SelectItem key="new">جديد</SelectItem>
          <SelectItem key="replied">تم الرد</SelectItem>
          <SelectItem key="resolved">مغلق</SelectItem>
        </Select>
      </div>

      {loading ? (
        <div className="flex justify-center p-12"><Spinner color="primary" label="جاري التحميل..." /></div>
      ) : comments.length === 0 ? (
        <EmptyState title="لا توجد تعليقات" hint="ستظهر التعليقات هنا فور وصولها من فيسبوك/إنستقرام." />
      ) : (
        <div className="space-y-3">
          {comments.map(c => (
            <div key={c.id} className="rounded-xl border border-default-200 p-4 space-y-3">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-2 flex-wrap">
                  <Chip size="sm" variant="flat" color={c.platform === 'instagram' ? 'secondary' : 'primary'}>
                    {c.platform === 'instagram' ? 'إنستقرام' : 'فيسبوك'}
                  </Chip>
                  <span className="font-medium">{c.author_name || 'مستخدم'}</span>
                  {c.sentiment && <Chip size="sm" color={SENT_TONE[c.sentiment] || 'default'} variant="dot">{c.sentiment}</Chip>}
                  {c.intent && <Chip size="sm" variant="flat">{c.intent}</Chip>}
                  {c.lead_temp && <Chip size="sm" color={LEAD_TONE[c.lead_temp] || 'default'} variant="flat">عميل {c.lead_temp} ({c.lead_score})</Chip>}
                </div>
                <Chip size="sm" variant="bordered">{STATUS_AR[c.status] || c.status}</Chip>
              </div>

              <p className="text-sm">{c.message}</p>

              {c.suggested_reply && c.status !== 'replied' && (
                <div className="rounded-lg bg-default-100 p-3 text-sm">
                  <span className="text-foreground-500">اقتراح الذكاء: </span>{c.suggested_reply}
                </div>
              )}
              {c.final_reply && (
                <div className="rounded-lg bg-success-50 p-3 text-sm">
                  <span className="text-foreground-500">الردّ المنشور: </span>{c.final_reply}
                </div>
              )}

              {canAct && c.status !== 'replied' && c.status !== 'resolved' && (
                <div className="space-y-2">
                  <Textarea minRows={1} placeholder="اكتب ردّاً..." value={draft[c.id] ?? c.suggested_reply ?? ''}
                    onValueChange={v => setDraft({ ...draft, [c.id]: v })} />
                  <div className="flex gap-2 flex-wrap">
                    <Button size="sm" color="primary" isLoading={busy === c.id}
                      onPress={() => act(c.id, 'reply', { text: draft[c.id] ?? c.suggested_reply ?? '' })}>إرسال</Button>
                    {c.suggested_reply && (
                      <Button size="sm" variant="flat" color="success" isLoading={busy === c.id}
                        onPress={() => act(c.id, 'approve')}>اعتماد الاقتراح</Button>
                    )}
                    <Button size="sm" variant="light" onPress={() => act(c.id, 'resolve')}>إغلاق</Button>
                    <Button size="sm" variant="light" color="warning" onPress={() => act(c.id, 'hide')}>إخفاء</Button>
                    <Button size="sm" variant="light" color="danger" onPress={() => act(c.id, 'ignore')}>تجاهل</Button>
                    {c.permalink && <Button size="sm" variant="light" as="a" href={c.permalink} target="_blank">فتح</Button>}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
