/**
 * Omni-channel Broadcast — free-text bulk send.
 *
 * Compose one message, pick which connected channels to send on, and fire.
 * Unlike WhatsApp Campaigns (template-based), this is free text to every
 * connected channel's active users. Shows live per-channel progress + history.
 */
import { useEffect, useState, useCallback } from 'react'
import { Button, Textarea, Checkbox, Chip, Spinner } from '@heroui/react'
import { api, ApiError, Broadcast as BroadcastT } from '../../api'
import { PageHeader, InlineAlert } from '../../components/ui'

const CHANNEL_LABELS: Record<string, string> = {
  widget:    'شات الموقع',
  telegram:  'تيليجرام',
  whatsapp:  'واتساب',
  messenger: 'ماسنجر',
  instagram: 'إنستجرام',
  email:     'البريد الإلكتروني',
}

const STATUS_LABELS: Record<BroadcastT['status'], string> = {
  draft: 'مسودة', sending: 'جارٍ الإرسال', sent: 'تم الإرسال', failed: 'فشل',
}
const STATUS_COLORS: Record<BroadcastT['status'], 'default' | 'warning' | 'success' | 'danger'> = {
  draft: 'default', sending: 'warning', sent: 'success', failed: 'danger',
}

function fmtDate(iso?: string) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ar-SA', { dateStyle: 'short', timeStyle: 'short' })
}

const MAX_LEN = 4000

export default function Broadcast({ storeId }: { storeId: string }) {
  const [channels, setChannels]   = useState<string[]>([])
  const [counts, setCounts]       = useState<Record<string, number>>({})
  const [selected, setSelected]   = useState<Set<string>>(new Set())
  const [message, setMessage]     = useState('')
  const [sending, setSending]     = useState(false)
  const [msg, setMsg]             = useState('')
  const [loadingAud, setLoadingAud] = useState(true)
  const [history, setHistory]     = useState<BroadcastT[]>([])

  const loadHistory = useCallback(async () => {
    try { setHistory((await api.listBroadcasts(storeId)).broadcasts) }
    catch { /* non-fatal */ }
  }, [storeId])

  useEffect(() => {
    let alive = true
    ;(async () => {
      setLoadingAud(true)
      try {
        const aud = await api.broadcastAudience(storeId)
        if (!alive) return
        setChannels(aud.channels)
        setCounts(aud.counts)
        setSelected(new Set(aud.channels))   // default: all connected
      } catch (e) {
        if (alive) setMsg(e instanceof ApiError ? e.message : 'تعذّر تحميل القنوات')
      } finally {
        if (alive) setLoadingAud(false)
      }
    })()
    loadHistory()
    return () => { alive = false }
  }, [storeId, loadHistory])

  function toggle(ch: string) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(ch) ? next.delete(ch) : next.add(ch)
      return next
    })
  }

  const totalReach = [...selected].reduce((sum, ch) => sum + (counts[ch] || 0), 0)

  async function send() {
    const text = message.trim()
    if (!text) { setMsg('اكتب نص الرسالة أولاً'); return }
    if (selected.size === 0) { setMsg('اختر قناة واحدة على الأقل'); return }
    setSending(true); setMsg('')
    try {
      await api.createBroadcast(storeId, text, [...selected])
      setMsg(`✅ بدأ الإرسال إلى ${totalReach} مستلم`)
      setMessage('')
      // Refresh history now + after a beat to catch the live progress.
      await loadHistory()
      setTimeout(loadHistory, 2500)
      setTimeout(loadHistory, 7000)
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : 'فشل الإرسال')
    } finally {
      setSending(false)
    }
  }

  return (
    <div dir="rtl" className="p-5 space-y-5">
      <PageHeader title="رسالة جماعية" subtitle="أرسل رسالة واحدة لكل عملائك عبر القنوات المربوطة" />

      {loadingAud ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : channels.length === 0 ? (
        <InlineAlert text="لا توجد قناة مربوطة بعد — اربط واتساب/تيليجرام/الإيميل من صفحة القنوات أولاً." />
      ) : (
        <div className="bg-content1 border border-divider rounded-xl p-5 space-y-4">
          <Textarea
            label="نص الرسالة"
            placeholder="اكتب رسالتك هنا…"
            value={message}
            onValueChange={setMessage}
            minRows={4}
            maxLength={MAX_LEN}
            description={`${message.length}/${MAX_LEN} حرف`}
          />

          <div>
            <p className="text-sm font-bold text-foreground mb-2">القنوات</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {channels.map(ch => (
                <label key={ch}
                  className="flex items-center gap-2 border border-divider rounded-lg px-3 py-2 cursor-pointer hover:bg-default-100">
                  <Checkbox isSelected={selected.has(ch)} onValueChange={() => toggle(ch)} />
                  <span className="text-sm font-semibold flex-1">{CHANNEL_LABELS[ch] || ch}</span>
                  <Chip size="sm" variant="flat">{counts[ch] ?? 0}</Chip>
                </label>
              ))}
            </div>
            <p className="text-xs text-default-400 mt-2">
              واتساب/ماسنجر/إنستجرام: تُرسل فقط لمن راسلك خلال آخر ٢٤ ساعة (سياسة Meta).
              للجمهور الأقدم استخدم «الحملات» بقالب معتمد.
            </p>
          </div>

          <InlineAlert text={msg} />

          <div className="flex items-center justify-between">
            <span className="text-sm text-default-500">
              الوصول التقديري: <b className="text-foreground">{totalReach}</b> مستلم
            </span>
            <Button color="primary" isLoading={sending} onPress={send}
              isDisabled={!message.trim() || selected.size === 0}
              startContent={!sending && (
                <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                  <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
                </svg>
              )}>
              {sending ? 'جارٍ الإرسال…' : 'إرسال الآن'}
            </Button>
          </div>
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm font-bold text-foreground">السجل</p>
          {history.map(b => (
            <div key={b.id} className="bg-content1 border border-divider rounded-lg p-3 flex items-start gap-3">
              <div className="flex-1 min-w-0">
                <p className="text-sm text-foreground line-clamp-2">{b.message}</p>
                <div className="flex flex-wrap items-center gap-2 mt-1.5">
                  <span className="text-xs text-default-400">{fmtDate(b.created_at)}</span>
                  {b.channels.map(ch => (
                    <Chip key={ch} size="sm" variant="flat" className="text-[10px]">
                      {CHANNEL_LABELS[ch] || ch}
                    </Chip>
                  ))}
                </div>
              </div>
              <div className="text-left shrink-0">
                <Chip size="sm" color={STATUS_COLORS[b.status]} variant="flat">
                  {STATUS_LABELS[b.status]}
                </Chip>
                <p className="text-xs text-default-500 mt-1">
                  {b.sent_count}/{b.total_count} ✓{b.failed_count ? ` · ${b.failed_count} ✗` : ''}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
