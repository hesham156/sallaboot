import { useEffect, useState, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Button, Input, Spinner, Textarea, Avatar,
  Modal, ModalBody, ModalContent, ModalFooter, ModalHeader,
} from '@heroui/react'
import { api, ConvSummary, Conversation, Message } from '../../api'

interface Props { storeId: string }

/* ── Icon helper ── */
function Icon({ paths, size = 16, className = '' }: {
  paths: string | string[]
  size?: number
  className?: string
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

/* ── Time helper ── */
function relTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 1000  // seconds
  if (diff < 60)     return 'الآن'
  if (diff < 3600)   return `منذ ${Math.floor(diff / 60)} د`
  if (diff < 86400)  return `منذ ${Math.floor(diff / 3600)} س`
  if (diff < 604800) return `منذ ${Math.floor(diff / 86400)} يوم`
  return d.toLocaleDateString('ar-SA', { day: 'numeric', month: 'short' })
}

function fmtTime(iso: string): string {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' })
}

/**
 * Parse a message body for markdown-style links `[text](url)` and render:
 *  - image attachments inline as thumbnails (clickable to open full size)
 *  - other files as clickable filename links
 *  - plain text unchanged
 *
 * Used so the admin can actually preview uploaded designs in the chat.
 */
function renderMessageBody(content: string): React.ReactNode {
  if (!content) return '(رسالة فارغة)'

  const linkRegex = /\[([^\]]+)\]\(([^)]+)\)/g
  const parts: React.ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = linkRegex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      parts.push(content.slice(lastIndex, match.index))
    }
    const [, text, url] = match
    const isImage = /\.(png|jpe?g|gif|webp|svg|bmp)(\?|$)/i.test(url) ||
                    url.includes('/file/')   // backend serves all uploads via /file/{id}
    if (isImage) {
      parts.push(
        <a
          key={`l${parts.length}`}
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="block mt-2 group"
        >
          <img
            src={url}
            alt={text}
            className="max-w-[240px] max-h-[200px] rounded-lg border border-white/20 object-cover group-hover:border-white/40 transition-colors"
            onError={(e) => {
              const img = e.currentTarget
              img.style.display = 'none'
              const fallback = img.nextElementSibling as HTMLElement | null
              if (fallback) fallback.style.display = 'inline-flex'
            }}
          />
          <span style={{ display: 'none' }} className="items-center gap-1.5 px-3 py-2 bg-white/10 rounded-lg text-xs">
            🖼️ {text} (الصورة غير متاحة — اضغط للتحميل)
          </span>
          <span className="block text-[10px] opacity-70 mt-1 truncate max-w-[240px]">{text}</span>
        </a>
      )
    } else {
      parts.push(
        <a
          key={`l${parts.length}`}
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-white/10 hover:bg-white/15 rounded-md mt-1 text-xs underline-offset-2 hover:underline"
        >
          📄 {text}
        </a>
      )
    }
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < content.length) {
    parts.push(content.slice(lastIndex))
  }
  return parts.length > 0 ? parts : content
}

export default function Conversations({ storeId }: Props) {
  const [convs, setConvs] = useState<ConvSummary[]>([])
  const [total, setTotal] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selected, setSelected] = useState<Conversation | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [replyText, setReplyText] = useState('')
  const [sending, setSending] = useState(false)
  const [search, setSearch] = useState('')
  const messagesRef = useRef<HTMLDivElement>(null)

  // End-conversation modal
  const DEFAULT_FAREWELL =
    'شكراً لتواصلكم معنا 🌷\nإذا كان لديكم أي استفسار آخر لا تترددوا بالتواصل معنا.\nنتمنى لكم يوماً سعيداً.'
  const [endOpen, setEndOpen]         = useState(false)
  const [farewell, setFarewell]       = useState(DEFAULT_FAREWELL)
  const [skipCsat, setSkipCsat]       = useState(false)
  const [endingChat, setEndingChat]   = useState(false)

  // Deep-link support: when arriving from Analytics → "Open conversation"
  // the page is loaded with ?session=<id> in the URL. We auto-open that
  // session once the list finishes loading so the admin lands directly
  // on the right transcript instead of having to search for it.
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedSession = searchParams.get('session')

  useEffect(() => { loadConversations() }, [storeId])
  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight
    }
  }, [selected?.messages])

  // Auto-open the requested session after the list loads.
  useEffect(() => {
    if (!requestedSession || loading) return
    if (selectedId === requestedSession) return
    const match = convs.find(c => c.session_id === requestedSession)
    if (match) {
      openConversation(match)
    } else {
      // Conversation not in the visible list (older / different page) —
      // fall back to fetching by id directly.
      setSelectedId(requestedSession)
      setDetailLoading(true)
      api.getConversation(storeId, requestedSession)
        .then(setSelected)
        .catch(console.error)
        .finally(() => setDetailLoading(false))
    }
    // Drop the query param so a refresh doesn't keep re-triggering.
    const next = new URLSearchParams(searchParams)
    next.delete('session')
    setSearchParams(next, { replace: true })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestedSession, loading, convs])

  async function loadConversations() {
    setLoading(true)
    try {
      const res = await api.listConversations(storeId)
      setConvs(res.conversations)
      setTotal(res.total)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  async function openConversation(c: ConvSummary) {
    setSelectedId(c.session_id)
    setDetailLoading(true)
    try {
      const detail = await api.getConversation(storeId, c.session_id)
      setSelected(detail)
    } catch (e) { console.error(e) }
    finally { setDetailLoading(false) }
  }

  async function sendReply() {
    if (!selected || !replyText.trim()) return
    setSending(true)
    try {
      await api.adminReply(storeId, selected.session_id, replyText.trim())
      setReplyText('')
      const updated = await api.getConversation(storeId, selected.session_id)
      setSelected(updated)
    } finally { setSending(false) }
  }

  async function handleTakeover() {
    if (!selected) return
    await api.takeover(storeId, selected.session_id)
    const updated = await api.getConversation(storeId, selected.session_id)
    setSelected(updated)
    loadConversations()
  }

  async function handleHandback() {
    if (!selected) return
    await api.handback(storeId, selected.session_id)
    const updated = await api.getConversation(storeId, selected.session_id)
    setSelected(updated)
    loadConversations()
  }

  function openEndModal() {
    setFarewell(DEFAULT_FAREWELL)
    setSkipCsat(false)
    setEndOpen(true)
  }

  async function confirmEndChat() {
    if (!selected) return
    setEndingChat(true)
    try {
      await api.endConversation(storeId, selected.session_id, {
        farewell:  farewell.trim() || undefined,
        skip_csat: skipCsat,
      })
      const updated = await api.getConversation(storeId, selected.session_id)
      setSelected(updated)
      loadConversations()
      setEndOpen(false)
    } catch (e) {
      alert(e instanceof Error ? e.message : 'تعذر إنهاء المحادثة')
    } finally { setEndingChat(false) }
  }

  const filtered = search
    ? convs.filter(c =>
        c.session_id.includes(search) ||
        c.last_message?.content?.toLowerCase().includes(search.toLowerCase())
      )
    : convs

  const unreadCount = convs.filter(c => c.unread).length

  return (
    <div className="flex h-screen" dir="rtl">

      {/* ════════════════ LIST PANEL (right side, RTL) ════════════════ */}
      <aside className="w-80 border-l border-divider bg-content2 flex flex-col flex-shrink-0">

        {/* List header */}
        <div className="px-4 py-3 border-b border-divider flex-shrink-0">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h1 className="text-base font-bold text-foreground flex items-center gap-2">
                المحادثات
                {unreadCount > 0 && (
                  <span className="text-[10px] bg-red-500 text-white rounded-full px-1.5 py-0.5 font-bold">
                    {unreadCount}
                  </span>
                )}
              </h1>
              <p className="text-[11px] text-slate-500 mt-0.5">{total} محادثة</p>
            </div>
            <button
              onClick={loadConversations}
              className="w-8 h-8 rounded-lg bg-content2 border border-divider flex items-center justify-center text-slate-400 hover:text-foreground hover:border-slate-500"
              title="تحديث"
            >
              <Icon paths="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" size={13} />
            </button>
          </div>

          <Input
            placeholder="بحث..."
            value={search}
            onValueChange={setSearch}
            variant="bordered"
            size="sm"
            classNames={{
              inputWrapper: 'border-divider bg-content2 h-9 min-h-9',
              input: 'text-xs text-foreground',
            }}
            startContent={
              <Icon paths={['M21 21l-4.35-4.35', 'M11 19a8 8 0 100-16 8 8 0 000 16z']}
                    size={12} className="text-slate-500 flex-shrink-0" />
            }
          />
        </div>

        {/* List items */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Spinner size="sm" color="primary" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
              <div className="w-12 h-12 rounded-2xl bg-content2 flex items-center justify-center mb-3">
                <Icon paths="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                      size={22} className="text-slate-600" />
              </div>
              <p className="text-sm text-slate-400 font-semibold">لا توجد محادثات</p>
              <p className="text-xs text-slate-600 mt-1">المحادثات الجديدة ستظهر هنا</p>
            </div>
          ) : (
            <div className="py-1">
              {filtered.map(c => {
                const isActive = selectedId === c.session_id
                const lastMsg = c.last_message
                const roleEmoji = !lastMsg ? '' :
                                  lastMsg.role === 'user'  ? '👤' :
                                  lastMsg.role === 'admin' ? '👨‍💼' : '🤖'
                return (
                  <button
                    key={c.session_id}
                    onClick={() => openConversation(c)}
                    className={`
                      w-full text-right px-4 py-3 border-b border-divider/40
                      transition-colors flex gap-3 items-start
                      ${isActive
                        ? 'bg-violet-500/10 border-r-2 border-r-violet-500'
                        : c.unread
                        ? 'bg-blue-500/5 hover:bg-content2'
                        : 'hover:bg-content2'
                      }
                    `}
                  >
                    {/* Avatar */}
                    <div className="relative flex-shrink-0">
                      <div className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold ${
                        c.bot_enabled
                          ? 'bg-gradient-to-br from-teal-500 to-cyan-600 text-white'
                          : 'bg-gradient-to-br from-amber-500 to-orange-600 text-white'
                      }`}>
                        {c.bot_enabled ? '🤖' : '👨‍💼'}
                      </div>
                      {c.unread && (
                        <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 bg-red-500 rounded-full border-2 border-content1" />
                      )}
                    </div>

                    {/* Body */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2 mb-0.5">
                        <span className="text-xs font-bold text-foreground truncate">
                          {c.session_id.slice(0, 8)}…
                        </span>
                        <span className="text-[10px] text-slate-500 flex-shrink-0">
                          {relTime(c.last_activity)}
                        </span>
                      </div>
                      <p className="text-xs text-slate-400 truncate leading-relaxed">
                        {lastMsg?.content
                          ? `${roleEmoji} ${lastMsg.content.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')}`
                          : 'لا توجد رسائل'}
                      </p>
                      <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${
                          c.bot_enabled
                            ? 'bg-blue-500/15 text-blue-400'
                            : 'bg-amber-500/15 text-amber-400'
                        }`}>
                          {c.bot_enabled ? 'بوت' : 'إدارة'}
                        </span>
                        {/* WhatsApp channel badge */}
                        {(c as any).channel === 'whatsapp' && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 font-semibold flex items-center gap-0.5">
                            <svg width={9} height={9} viewBox="0 0 24 24" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/><path d="M12 0C5.373 0 0 5.373 0 12c0 2.12.554 4.106 1.521 5.836L.057 23.887l6.217-1.432A11.946 11.946 0 0012 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 21.894a9.877 9.877 0 01-5.042-1.381l-.361-.214-3.741.981.998-3.645-.235-.374A9.862 9.862 0 012.116 12C2.116 6.548 6.548 2.116 12 2.116c5.452 0 9.884 4.432 9.884 9.884 0 5.452-4.432 9.894-9.884 9.894z"/></svg>
                            WA
                          </span>
                        )}
                        <span className="text-[10px] text-slate-600">
                          {c.messages_count} رسالة
                        </span>
                        {c.rating && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-semibold">
                            {c.rating}★
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </aside>

      {/* ════════════════ CHAT PANEL (left side, RTL) ════════════════ */}
      <main className="flex-1 flex flex-col bg-content2 min-w-0">
        {!selected ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center px-6">
            <div className="w-20 h-20 rounded-3xl bg-content1 border border-divider flex items-center justify-center mb-4">
              <Icon paths="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                    size={36} className="text-slate-600" />
            </div>
            <p className="text-base font-semibold text-slate-400">اختر محادثة لعرضها</p>
            <p className="text-xs text-slate-600 mt-1">اضغط على أي محادثة من القائمة على اليمين</p>
          </div>
        ) : detailLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <Spinner size="lg" color="primary" />
          </div>
        ) : (
          <>
            {/* Chat header */}
            <header className="px-5 py-3 border-b border-divider bg-content1 flex-shrink-0">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3 min-w-0">
                  <Avatar
                    name={selected.session_id[0]}
                    size="sm"
                    className={selected.bot_enabled
                      ? 'bg-gradient-to-br from-teal-500 to-cyan-600 text-white'
                      : 'bg-gradient-to-br from-amber-500 to-orange-600 text-white'}
                  />
                  <div className="min-w-0">
                    <p className="text-sm font-bold text-foreground truncate">
                      {selected.customer_info?.name || `جلسة ${selected.session_id.slice(0, 8)}`}
                    </p>
                    <div className="flex items-center gap-2 text-xs">
                      <span className={`flex items-center gap-1 ${
                        selected.bot_enabled ? 'text-blue-400' : 'text-amber-400'
                      }`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${
                          selected.bot_enabled ? 'bg-blue-400' : 'bg-amber-400'
                        }`} />
                        {selected.bot_enabled ? 'البوت يتولى' : 'الإدارة تتولى'}
                      </span>
                      {selected.customer_info?.phone && (
                        <span className="text-slate-500">📱 {selected.customer_info.phone}</span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex gap-2 flex-shrink-0 flex-wrap justify-end">
                  {selected.bot_enabled ? (
                    <Button
                      size="sm" color="warning" variant="flat"
                      onPress={handleTakeover}
                      startContent={<Icon paths="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" size={13} />}
                    >
                      تولي المحادثة
                    </Button>
                  ) : (
                    <Button
                      size="sm" color="success" variant="flat"
                      onPress={handleHandback}
                      startContent={<Icon paths="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" size={13} />}
                    >
                      إعادة للبوت
                    </Button>
                  )}
                  {!selected.bot_enabled && (
                    <Button
                      size="sm" variant="flat"
                      onPress={openEndModal}
                      startContent={<Icon paths={['M5 13l4 4L19 7']} size={13} />}
                      className="bg-teal-500/15 text-teal-500 hover:bg-teal-500/25"
                    >
                      إنهاء + تقييم
                    </Button>
                  )}
                </div>
              </div>
            </header>

            {/* Messages */}
            <div
              ref={messagesRef}
              className="flex-1 overflow-y-auto px-5 py-4 space-y-3"
            >
              {selected.messages?.length === 0 ? (
                <div className="flex items-center justify-center py-12">
                  <p className="text-sm text-slate-500">لا توجد رسائل بعد</p>
                </div>
              ) : (
                selected.messages?.map((msg: Message, i: number) => {
                  const isUser  = msg.role === 'user'
                  const isAdmin = msg.role === 'admin'
                  const isCsat  = msg.meta?.kind === 'csat'
                  const empName = msg.employee_name
                  return (
                    <div
                      key={i}
                      className={`flex gap-2 ${isUser ? 'justify-start' : 'justify-end'}`}
                    >
                      {/* Avatar (left for bot/admin, right for user — visually) */}
                      {!isUser && (
                        <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${
                          isAdmin
                            ? 'bg-amber-500/20 text-amber-400'
                            : isCsat
                            ? 'bg-teal-500/20 text-teal-400'
                            : 'bg-blue-500/20 text-blue-400'
                        }`}>
                          {isAdmin ? (empName ? empName.trim().charAt(0) : '👨‍💼')
                                   : isCsat ? '⭐' : '🤖'}
                        </div>
                      )}

                      <div className={`
                        max-w-[70%] min-w-[80px] rounded-2xl px-4 py-2.5 text-sm leading-relaxed
                        ${isUser
                          ? 'bg-gradient-to-br from-teal-600 to-cyan-700 text-white rounded-tr-sm'
                          : isAdmin
                          ? 'bg-amber-50 text-amber-900 border border-amber-200 rounded-tl-sm'
                          : isCsat
                          ? 'bg-teal-500/10 text-teal-900 border border-teal-500/30 rounded-tl-sm'
                          : 'bg-content1 text-foreground border border-divider rounded-tl-sm'
                        }
                      `}>
                        {isAdmin && (
                          <p className="text-[10px] text-amber-600 mb-1 font-bold">
                            {empName ? `${empName} · موظف` : 'الإدارة'}
                          </p>
                        )}
                        {isCsat && (
                          <p className="text-[10px] text-teal-600 mb-1 font-bold">
                            استطلاع رضا
                          </p>
                        )}
                        <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                          {renderMessageBody(msg.content)}
                        </div>
                        {isCsat && msg.meta?.options && (
                          <div className="flex flex-wrap gap-1.5 mt-2">
                            {msg.meta.options.map(opt => (
                              <span
                                key={opt.value}
                                className="text-[11px] px-2 py-1 rounded-full bg-white/70 border border-teal-500/30 text-teal-700"
                              >
                                {opt.label}
                              </span>
                            ))}
                          </div>
                        )}
                        <p className={`text-[10px] mt-1 ${
                          isUser ? 'text-white/70' : 'text-slate-500'
                        }`}>
                          {fmtTime(msg.ts)}
                        </p>
                      </div>

                      {isUser && (
                        <div className="w-7 h-7 rounded-full bg-blue-500/20 text-blue-400 flex items-center justify-center text-xs font-bold flex-shrink-0">
                          👤
                        </div>
                      )}
                    </div>
                  )
                })
              )}
            </div>

            {/* Reply input — only when admin took over */}
            {!selected.bot_enabled && (
              <footer className="px-4 py-3 border-t border-divider bg-content1 flex-shrink-0">
                <div className="flex gap-2">
                  <Textarea
                    placeholder="اكتب ردك كأدمن..."
                    value={replyText}
                    onValueChange={setReplyText}
                    variant="bordered"
                    minRows={1}
                    maxRows={4}
                    classNames={{
                      inputWrapper: 'border-divider bg-content2',
                      input: 'text-sm',
                    }}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        sendReply()
                      }
                    }}
                  />
                  <Button
                    color="primary"
                    isLoading={sending}
                    isIconOnly
                    onPress={sendReply}
                    isDisabled={!replyText.trim()}
                    className="self-end h-10 w-10 min-w-10 bg-gradient-to-br from-teal-600 to-cyan-700"
                  >
                    <Icon paths={['M22 2L11 13', 'M22 2l-7 20-4-9-9-4 20-7z']} size={15} />
                  </Button>
                </div>
                <p className="text-[10px] text-slate-600 mt-1.5 px-1">
                  Enter للإرسال · Shift+Enter لسطر جديد
                </p>
              </footer>
            )}

            {/* Banner when bot is in control */}
            {selected.bot_enabled && (
              <footer className="px-4 py-3 border-t border-divider bg-blue-500/5 flex-shrink-0">
                <p className="text-xs text-blue-300/80 text-center">
                  🤖 البوت يتولى هذه المحادثة. اضغط <span className="font-bold">تولي المحادثة</span> للرد كأدمن.
                </p>
              </footer>
            )}
          </>
        )}
      </main>

      {/* ════════════════ END-CONVERSATION MODAL ════════════════ */}
      <Modal
        isOpen={endOpen}
        onOpenChange={setEndOpen}
        placement="center"
        backdrop="blur"
        size="md"
      >
        <ModalContent>
          {() => (
            <>
              <ModalHeader className="flex flex-col gap-1">
                <span className="text-base font-bold">إنهاء المحادثة</span>
                <span className="text-xs text-slate-500 font-normal">
                  هنرسل وداع باسمك، رسالة شكر من المساعد، ثم استطلاع تقييم للعميل.
                </span>
              </ModalHeader>
              <ModalBody className="space-y-3" dir="rtl">
                <Textarea
                  label="رسالة الوداع"
                  value={farewell}
                  onValueChange={setFarewell}
                  variant="bordered"
                  minRows={3}
                  maxRows={6}
                />
                <label className="flex items-center gap-2 text-xs text-slate-500 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={skipCsat}
                    onChange={e => setSkipCsat(e.target.checked)}
                  />
                  لا ترسل استطلاع التقييم بعد الوداع
                </label>
                <div className="text-[11px] text-slate-500 bg-content2 rounded-xl p-3 leading-relaxed">
                  بعد الإنهاء سيتلقى العميل:
                  <ol className="list-decimal mr-5 mt-1 space-y-0.5">
                    <li>رسالتك أعلاه (تظهر باسمك إن كنت موظفاً)</li>
                    <li>رسالة شكر من المساعد الذكي</li>
                    {!skipCsat && <li>أزرار تقييم (راضٍ تماماً / راضٍ / محايد / غير راضٍ …)</li>}
                  </ol>
                </div>
              </ModalBody>
              <ModalFooter>
                <Button variant="light" onPress={() => setEndOpen(false)}>إلغاء</Button>
                <Button
                  color="primary"
                  isLoading={endingChat}
                  onPress={confirmEndChat}
                  className="bg-gradient-to-br from-teal-600 to-cyan-700 text-white font-bold"
                  startContent={<Icon paths={['M5 13l4 4L19 7']} size={13} />}
                >
                  إنهاء وإرسال
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>
    </div>
  )
}

