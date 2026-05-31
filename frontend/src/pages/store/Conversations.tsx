import { useEffect, useState, useRef } from 'react'
import {
  Button, Input, Spinner, Textarea, Avatar,
} from '@heroui/react'
import { api, ConvSummary, Conversation } from '../../api'

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

  useEffect(() => { loadConversations() }, [storeId])
  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight
    }
  }, [selected?.messages])

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
      <aside className="w-80 border-l border-[#1c2d42] bg-[#0a1422] flex flex-col flex-shrink-0">

        {/* List header */}
        <div className="px-4 py-3 border-b border-[#1c2d42] flex-shrink-0">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h1 className="text-base font-bold text-white flex items-center gap-2">
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
              className="w-8 h-8 rounded-lg bg-[#111e32] border border-[#1c2d42] flex items-center justify-center text-slate-400 hover:text-white hover:border-slate-500"
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
              inputWrapper: 'border-[#1c2d42] bg-[#111e32] h-9 min-h-9',
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
              <div className="w-12 h-12 rounded-2xl bg-[#111e32] flex items-center justify-center mb-3">
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
                      w-full text-right px-4 py-3 border-b border-[#1c2d42]/40
                      transition-colors flex gap-3 items-start
                      ${isActive
                        ? 'bg-violet-500/10 border-r-2 border-r-violet-500'
                        : c.unread
                        ? 'bg-blue-500/5 hover:bg-[#111e32]'
                        : 'hover:bg-[#111e32]'
                      }
                    `}
                  >
                    {/* Avatar */}
                    <div className="relative flex-shrink-0">
                      <div className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold ${
                        c.bot_enabled
                          ? 'bg-gradient-to-br from-blue-500 to-indigo-600 text-white'
                          : 'bg-gradient-to-br from-amber-500 to-orange-600 text-white'
                      }`}>
                        {c.bot_enabled ? '🤖' : '👨‍💼'}
                      </div>
                      {c.unread && (
                        <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 bg-red-500 rounded-full border-2 border-[#0a1422]" />
                      )}
                    </div>

                    {/* Body */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2 mb-0.5">
                        <span className="text-xs font-bold text-white truncate">
                          {c.session_id.slice(0, 8)}…
                        </span>
                        <span className="text-[10px] text-slate-500 flex-shrink-0">
                          {relTime(c.last_activity)}
                        </span>
                      </div>
                      <p className="text-xs text-slate-400 truncate leading-relaxed">
                        {lastMsg?.content
                          ? `${roleEmoji} ${lastMsg.content}`
                          : 'لا توجد رسائل'}
                      </p>
                      <div className="flex items-center gap-1.5 mt-1.5">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${
                          c.bot_enabled
                            ? 'bg-blue-500/15 text-blue-400'
                            : 'bg-amber-500/15 text-amber-400'
                        }`}>
                          {c.bot_enabled ? 'بوت' : 'إدارة'}
                        </span>
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
      <main className="flex-1 flex flex-col bg-[#070d17] min-w-0">
        {!selected ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center px-6">
            <div className="w-20 h-20 rounded-3xl bg-[#0c1627] border border-[#1c2d42] flex items-center justify-center mb-4">
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
            <header className="px-5 py-3 border-b border-[#1c2d42] bg-[#0c1627] flex-shrink-0">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3 min-w-0">
                  <Avatar
                    name={selected.session_id[0]}
                    size="sm"
                    className={selected.bot_enabled
                      ? 'bg-gradient-to-br from-blue-500 to-indigo-600 text-white'
                      : 'bg-gradient-to-br from-amber-500 to-orange-600 text-white'}
                  />
                  <div className="min-w-0">
                    <p className="text-sm font-bold text-white truncate">
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

                <div className="flex gap-2 flex-shrink-0">
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
                selected.messages?.map((msg, i) => {
                  const isUser  = msg.role === 'user'
                  const isAdmin = msg.role === 'admin'
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
                            : 'bg-blue-500/20 text-blue-400'
                        }`}>
                          {isAdmin ? '👨‍💼' : '🤖'}
                        </div>
                      )}

                      <div className={`
                        max-w-[70%] min-w-[80px] rounded-2xl px-4 py-2.5 text-sm leading-relaxed
                        ${isUser
                          ? 'bg-gradient-to-br from-blue-600 to-indigo-700 text-white rounded-tr-sm'
                          : isAdmin
                          ? 'bg-amber-500/15 text-amber-100 border border-amber-500/30 rounded-tl-sm'
                          : 'bg-[#0c1627] text-slate-200 border border-[#1c2d42] rounded-tl-sm'
                        }
                      `}>
                        {isAdmin && (
                          <p className="text-[10px] text-amber-400 mb-1 font-bold">الإدارة</p>
                        )}
                        <p style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                          {msg.content || '(رسالة فارغة)'}
                        </p>
                        <p className={`text-[10px] mt-1 ${
                          isUser ? 'text-blue-200' : 'text-slate-500'
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
              <footer className="px-4 py-3 border-t border-[#1c2d42] bg-[#0c1627] flex-shrink-0">
                <div className="flex gap-2">
                  <Textarea
                    placeholder="اكتب ردك كأدمن..."
                    value={replyText}
                    onValueChange={setReplyText}
                    variant="bordered"
                    minRows={1}
                    maxRows={4}
                    classNames={{
                      inputWrapper: 'border-[#1c2d42] bg-[#111e32]',
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
                    className="self-end h-10 w-10 min-w-10 bg-gradient-to-br from-blue-600 to-indigo-700"
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
              <footer className="px-4 py-3 border-t border-[#1c2d42] bg-blue-500/5 flex-shrink-0">
                <p className="text-xs text-blue-300/80 text-center">
                  🤖 البوت يتولى هذه المحادثة. اضغط <span className="font-bold">تولي المحادثة</span> للرد كأدمن.
                </p>
              </footer>
            )}
          </>
        )}
      </main>
    </div>
  )
}

