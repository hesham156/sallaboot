import { useEffect, useState, useRef } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import {
  Button, Input, Spinner, Textarea, Avatar,
  Modal, ModalBody, ModalContent, ModalFooter, ModalHeader,
} from '@heroui/react'
import { api, ApiError, AIConfig, Employee, ConvSummary, Conversation, Message, openAdminStream } from '../../api'

interface Props { storeId: string }

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

function WaIcon({ size = 12 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="#25D366" className="flex-shrink-0">
      <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z" />
      <path d="M12 0C5.373 0 0 5.373 0 12c0 2.12.554 4.106 1.521 5.836L.057 23.887l6.217-1.432A11.946 11.946 0 0012 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 21.894a9.877 9.877 0 01-5.042-1.381l-.361-.214-3.741.981.998-3.645-.235-.374A9.862 9.862 0 012.116 12C2.116 6.548 6.548 2.116 12 2.116c5.452 0 9.884 4.432 9.884 9.884 0 5.452-4.432 9.894-9.884 9.894z" />
    </svg>
  )
}

function IgIcon({ size = 12 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className="flex-shrink-0">
      <defs>
        <linearGradient id="ig-g" x1="0%" y1="100%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#f09433" />
          <stop offset="50%" stopColor="#dc2743" />
          <stop offset="100%" stopColor="#bc1888" />
        </linearGradient>
      </defs>
      <path fill="url(#ig-g)" d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z" />
    </svg>
  )
}

function detectChannel(c: { channel?: string; session_id: string }): string {
  if (c.channel === 'whatsapp' || c.session_id.startsWith('wa:'))        return 'whatsapp'
  if (c.channel === 'instagram' || c.session_id.startsWith('ig:'))       return 'instagram'
  if (c.channel === 'widget'    || c.session_id.startsWith('widget:'))   return 'widget'
  return c.channel || 'widget'
}

function relTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60)     return 'الآن'
  if (diff < 3600)   return `${Math.floor(diff / 60)}د`
  if (diff < 86400)  return `${Math.floor(diff / 3600)}س`
  if (diff < 604800) return `${Math.floor(diff / 86400)}ي`
  return d.toLocaleDateString('ar-SA', { day: 'numeric', month: 'short' })
}

function fmtTime(iso: string): string {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' })
}

function customerDisplayName(c: { customer_info?: { name?: string; phone?: string } | null; session_id: string }): string {
  const ci = c.customer_info
  if (ci?.name)  return ci.name
  if (ci?.phone) return ci.phone
  if (c.session_id.startsWith('wa:')) return '+' + c.session_id.slice(3)
  return `جلسة ${c.session_id.slice(0, 8)}`
}

function renderMessageBody(content: string): React.ReactNode {
  if (!content) return '(رسالة فارغة)'
  const linkRegex = /\[([^\]]+)\]\(([^)]+)\)/g
  const parts: React.ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = linkRegex.exec(content)) !== null) {
    if (match.index > lastIndex) parts.push(content.slice(lastIndex, match.index))
    const [, text, url] = match
    const isImage = /\.(png|jpe?g|gif|webp|svg|bmp)(\?|$)/i.test(url) || url.includes('/file/')
    if (isImage) {
      parts.push(
        <a key={`l${parts.length}`} href={url} target="_blank" rel="noopener noreferrer" className="block mt-2 group">
          <img src={url} alt={text}
            className="max-w-[240px] max-h-[200px] rounded-lg border border-white/20 object-cover group-hover:border-white/40 transition-colors"
            onError={(e) => {
              const img = e.currentTarget; img.style.display = 'none'
              const fb = img.nextElementSibling as HTMLElement | null
              if (fb) fb.style.display = 'inline-flex'
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
        <a key={`l${parts.length}`} href={url} target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-white/10 hover:bg-white/15 rounded-md mt-1 text-xs underline-offset-2 hover:underline">
          📄 {text}
        </a>
      )
    }
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < content.length) parts.push(content.slice(lastIndex))
  return parts.length > 0 ? parts : content
}

type ViewMode      = 'all' | 'mentions' | 'unattended' | 'chatbot'
type ActiveTab     = 'mine' | 'unassigned' | 'all'
type SortOrder     = 'last_activity' | 'newest' | 'oldest'
type StatusFilter  = 'open' | 'unread' | 'bot' | 'human'

export default function Conversations({ storeId }: Props) {
  const navigate = useNavigate()
  const [convs, setConvs]           = useState<ConvSummary[]>([])
  const [total, setTotal]           = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selected, setSelected]     = useState<Conversation | null>(null)
  const [loading, setLoading]       = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [replyText, setReplyText]   = useState('')
  const [sending, setSending]       = useState(false)
  const [search, setSearch]         = useState('')
  const [actionError, setActionError] = useState('')
  const messagesRef = useRef<HTMLDivElement>(null)
  const listRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Sidebar / filter state ──
  const [navCollapsed, setNavCollapsed] = useState(false)
  const [viewMode, setViewMode]         = useState<ViewMode>('all')
  const [activeTab, setActiveTab]       = useState<ActiveTab>('all')
  const [sortOrder, setSortOrder]       = useState<SortOrder>('last_activity')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('open')
  const [channelFilter, setChannelFilter] = useState<string | null>(null)
  const [empFilter, setEmpFilter]       = useState<number | null>(null)
  const [showSortMenu, setShowSortMenu]   = useState(false)
  const [showStatusMenu, setShowStatusMenu] = useState(false)
  const [assigningId, setAssigningId]   = useState<string | null>(null)
  const [teamsOpen, setTeamsOpen]       = useState(true)
  const [chOpen, setChOpen]             = useState(true)
  const [employees, setEmployees]       = useState<Employee[]>([])
  const [aiConfig, setAiConfig]         = useState<AIConfig | null>(null)

  const sortMenuRef   = useRef<HTMLDivElement>(null)
  const statusMenuRef = useRef<HTMLDivElement>(null)
  const assignRef     = useRef<HTMLDivElement>(null)

  function scheduleListRefresh(delay = 500) {
    if (listRefreshTimer.current) return
    listRefreshTimer.current = setTimeout(() => {
      listRefreshTimer.current = null
      loadConversations()
    }, delay)
  }

  // ── Access-reason gating ──
  const [accessReason, setAccessReason]       = useState('')
  const [reasonModalOpen, setReasonModalOpen] = useState(false)
  const [reasonDraft, setReasonDraft]         = useState('')
  const reasonResolverRef = useRef<((r: string | null) => void) | null>(null)

  function promptReason(): Promise<string | null> {
    setReasonDraft('')
    setReasonModalOpen(true)
    return new Promise<string | null>((resolve) => { reasonResolverRef.current = resolve })
  }

  async function fetchConv(sessionId: string): Promise<Conversation> {
    try {
      return await api.getConversation(storeId, sessionId, accessReason || undefined)
    } catch (e) {
      if (e instanceof ApiError && e.status === 403 && e.detail === 'reason_required') {
        const r = await promptReason()
        if (!r) throw e
        setAccessReason(r)
        return api.getConversation(storeId, sessionId, r)
      }
      throw e
    }
  }

  // ── End-conversation modal ──
  const DEFAULT_FAREWELL = 'شكراً لتواصلكم معنا 🌷\nإذا كان لديكم أي استفسار آخر لا تترددوا بالتواصل معنا.\nنتمنى لكم يوماً سعيداً.'
  const [endOpen, setEndOpen]       = useState(false)
  const [farewell, setFarewell]     = useState(DEFAULT_FAREWELL)
  const [skipCsat, setSkipCsat]     = useState(false)
  const [endingChat, setEndingChat] = useState(false)

  const [searchParams, setSearchParams] = useSearchParams()
  const requestedSession = searchParams.get('session')

  const selectedIdRef = useRef<string | null>(null)
  useEffect(() => { selectedIdRef.current = selectedId }, [selectedId])

  useEffect(() => { loadConversations() }, [storeId])

  useEffect(() => {
    api.listEmployees(storeId).then(r => setEmployees(r.employees)).catch(console.error)
    api.getAI(storeId).then(setAiConfig).catch(console.error)
  }, [storeId])

  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight
    }
  }, [selected?.messages])

  // Close dropdowns on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (sortMenuRef.current && !sortMenuRef.current.contains(e.target as Node)) {
        setShowSortMenu(false)
      }
      if (statusMenuRef.current && !statusMenuRef.current.contains(e.target as Node)) {
        setShowStatusMenu(false)
      }
      if (assignRef.current && !assignRef.current.contains(e.target as Node)) {
        setAssigningId(null)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => {
    if (!storeId) return
    const close = openAdminStream(storeId, {
      onMessage: (ev) => {
        if (ev.session_id === selectedIdRef.current) {
          fetchConv(ev.session_id).then(setSelected).catch(() => {})
        }
        scheduleListRefresh()
      },
      onNewConversation: () => scheduleListRefresh(),
      onRating:          () => scheduleListRefresh(),
      onBotToggle:       () => scheduleListRefresh(),
    }, { reason: accessReason || undefined })
    return () => {
      close()
      if (listRefreshTimer.current) { clearTimeout(listRefreshTimer.current); listRefreshTimer.current = null }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeId, accessReason])

  useEffect(() => {
    if (!requestedSession || loading) return
    if (selectedId === requestedSession) return
    const match = convs.find(c => c.session_id === requestedSession)
    if (match) {
      openConversation(match)
    } else {
      setSelectedId(requestedSession)
      setDetailLoading(true)
      fetchConv(requestedSession).then(setSelected).catch(console.error).finally(() => setDetailLoading(false))
    }
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
    setActionError('')
    setAssigningId(null)
    setSelectedId(c.session_id)
    setDetailLoading(true)
    try {
      const detail = await fetchConv(c.session_id)
      setSelected(detail)
    } catch (e) {
      console.error(e); setSelectedId(null); setSelected(null)
    } finally { setDetailLoading(false) }
  }

  async function sendReply() {
    if (!selected || !replyText.trim()) return
    setSending(true); setActionError('')
    try {
      await api.adminReply(storeId, selected.session_id, replyText.trim())
      setReplyText('')
      const updated = await fetchConv(selected.session_id)
      setSelected(updated)
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'تعذر إرسال الرد')
    } finally { setSending(false) }
  }

  async function handleTakeover() {
    if (!selected) return; setActionError('')
    try {
      await api.takeover(storeId, selected.session_id)
      const updated = await fetchConv(selected.session_id)
      setSelected(updated); loadConversations()
    } catch (e) { setActionError(e instanceof Error ? e.message : 'تعذر تولّي المحادثة') }
  }

  async function handleHandback() {
    if (!selected) return; setActionError('')
    try {
      await api.handback(storeId, selected.session_id)
      const updated = await fetchConv(selected.session_id)
      setSelected(updated); loadConversations()
    } catch (e) { setActionError(e instanceof Error ? e.message : 'تعذر إرجاع المحادثة للبوت') }
  }

  function openEndModal() { setFarewell(DEFAULT_FAREWELL); setSkipCsat(false); setEndOpen(true) }

  async function confirmEndChat() {
    if (!selected) return; setEndingChat(true)
    try {
      await api.endConversation(storeId, selected.session_id, { farewell: farewell.trim() || undefined, skip_csat: skipCsat })
      const updated = await fetchConv(selected.session_id)
      setSelected(updated); loadConversations(); setEndOpen(false)
    } catch (e) { alert(e instanceof Error ? e.message : 'تعذر إنهاء المحادثة') }
    finally { setEndingChat(false) }
  }

  // ── Filtering + sorting pipeline ──
  const mineCount       = convs.filter(c => !c.bot_enabled).length
  const unassignedCount = convs.filter(c => c.bot_enabled).length
  const unreadCount     = convs.filter(c => c.unread).length

  // 1. View-mode filter
  const viewFiltered: ConvSummary[] = (() => {
    if (viewMode === 'unattended') return convs.filter(c => c.unread)
    if (viewMode === 'chatbot')    return convs.filter(c => c.bot_enabled)
    if (viewMode === 'mentions')   return []
    return convs
  })()

  // 2. Tab filter (only when viewMode === 'all')
  const tabFiltered: ConvSummary[] = viewMode !== 'all' ? viewFiltered : (
    activeTab === 'mine'       ? convs.filter(c => !c.bot_enabled) :
    activeTab === 'unassigned' ? convs.filter(c => c.bot_enabled)  :
    convs
  )

  // 3. Channel filter (sidebar channel click)
  const chFiltered = channelFilter
    ? tabFiltered.filter(c => detectChannel(c) === channelFilter)
    : tabFiltered

  // 4. Employee filter (sidebar employee click — filters by last admin message name)
  const empFiltered = (empFilter !== null)
    ? chFiltered.filter(c => !c.bot_enabled)   // simplified: show human-handled convs for that agent
    : chFiltered

  // 5. Status filter
  const statusFiltered = (() => {
    if (statusFilter === 'unread') return empFiltered.filter(c => c.unread)
    if (statusFilter === 'bot')    return empFiltered.filter(c => c.bot_enabled)
    if (statusFilter === 'human')  return empFiltered.filter(c => !c.bot_enabled)
    return empFiltered
  })()

  // 6. Search
  const searchFiltered = search
    ? statusFiltered.filter(c =>
        c.session_id.includes(search) ||
        customerDisplayName(c).toLowerCase().includes(search.toLowerCase()) ||
        c.last_message?.content?.toLowerCase().includes(search.toLowerCase())
      )
    : statusFiltered

  // 7. Sort
  const filtered = [...searchFiltered].sort((a, b) => {
    if (sortOrder === 'newest') return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    if (sortOrder === 'oldest') return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    return new Date(b.last_activity).getTime() - new Date(a.last_activity).getTime()
  })

  function channelLabel(ch: string): string {
    if (ch === 'whatsapp')  return aiConfig?.whatsapp_phone_id ? `+${aiConfig.whatsapp_phone_id}` : 'واتساب'
    if (ch === 'instagram') return aiConfig?.ig_username || 'إنستقرام'
    return 'ويدجت'
  }

  const statusLabels: Record<StatusFilter, string> = {
    open:   'مفتوحة',
    unread: 'غير مقروءة',
    bot:    'مع البوت',
    human:  'مع إنسان',
  }

  const sortLabels: Record<SortOrder, string> = {
    last_activity: 'آخر نشاط',
    newest:        'الأحدث',
    oldest:        'الأقدم',
  }

  const navItems: { id: ViewMode; label: string; icon: string; count?: number }[] = [
    { id: 'all',        label: 'كل المحادثات',  count: total,
      icon: 'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z' },
    { id: 'mentions',   label: 'المذكورات',
      icon: 'M16 12a4 4 0 10-8 0 4 4 0 008 0zm0 0v1.5a2.5 2.5 0 005 0V12a9 9 0 10-9 9m4.5-1.206a8.959 8.959 0 01-4.5 1.207' },
    { id: 'unattended', label: 'غير المتابعة',  count: unreadCount,
      icon: 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z' },
    { id: 'chatbot',    label: 'البوت',          count: convs.filter(c => c.bot_enabled).length,
      icon: 'M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17H3a2 2 0 01-2-2V5a2 2 0 012-2h16a2 2 0 012 2v10a2 2 0 01-2 2h-2' },
  ]

  function toggleChannelFilter(ch: string) {
    setChannelFilter(prev => prev === ch ? null : ch)
    setViewMode('all')
  }

  function toggleEmpFilter(id: number) {
    setEmpFilter(prev => prev === id ? null : id)
    setViewMode('all')
  }

  return (
    <div className="flex h-screen overflow-hidden" dir="rtl">

      {/* ══════════════════════ NAV SIDEBAR ══════════════════════ */}
      <nav className={`shrink-0 bg-[#0f1729] flex flex-col border-l border-white/5 overflow-y-auto transition-all duration-200 ${navCollapsed ? 'w-0 overflow-hidden' : 'w-52'}`}>

        {/* Main nav */}
        <div className="py-2">
          {navItems.map(item => (
            <button
              key={item.id}
              onClick={() => { setViewMode(item.id); setChannelFilter(null); setEmpFilter(null) }}
              className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-xs transition-colors ${
                viewMode === item.id && !channelFilter && empFilter === null
                  ? 'bg-indigo-600/20 text-indigo-300 font-semibold'
                  : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
              }`}
            >
              <Icon paths={item.icon} size={14} className="flex-shrink-0" />
              <span className="flex-1 text-right">{item.label}</span>
              {!!item.count && (
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-bold ${
                  viewMode === item.id && !channelFilter && empFilter === null
                    ? 'bg-indigo-500 text-white'
                    : 'bg-white/10 text-slate-400'
                }`}>
                  {item.count}
                </span>
              )}
            </button>
          ))}
        </div>

        <div className="border-t border-white/5 my-1 mx-3" />

        {/* Teams / employees */}
        <div className="py-1">
          <button
            onClick={() => setTeamsOpen(o => !o)}
            className="w-full flex items-center justify-between px-3 py-2 text-[10px] font-bold text-slate-500 uppercase tracking-widest hover:text-slate-300"
          >
            <span>الفريق</span>
            <Icon paths={teamsOpen ? 'M5 15l7-7 7 7' : 'M19 9l-7 7-7-7'} size={10} />
          </button>
          {teamsOpen && (
            <>
              {employees.map(emp => (
                <button key={emp.id}
                  onClick={() => toggleEmpFilter(emp.id)}
                  className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs transition-colors ${
                    empFilter === emp.id
                      ? 'bg-indigo-600/20 text-indigo-300'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'
                  }`}>
                  <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0 ${
                    empFilter === emp.id ? 'bg-indigo-500 text-white' : 'bg-indigo-500/20 text-indigo-400'
                  }`}>
                    {emp.name.charAt(0)}
                  </div>
                  <span className="truncate">{emp.name}</span>
                  {empFilter === emp.id && (
                    <span className="text-[10px] text-indigo-400 ml-auto">{filtered.length}</span>
                  )}
                </button>
              ))}
              {employees.length === 0 && (
                <p className="px-3 py-1.5 text-[10px] text-slate-600 text-right">لا يوجد موظفون</p>
              )}
            </>
          )}
        </div>

        <div className="border-t border-white/5 my-1 mx-3" />

        {/* Channels */}
        <div className="py-1">
          <button
            onClick={() => setChOpen(o => !o)}
            className="w-full flex items-center justify-between px-3 py-2 text-[10px] font-bold text-slate-500 uppercase tracking-widest hover:text-slate-300"
          >
            <span>القنوات</span>
            <Icon paths={chOpen ? 'M5 15l7-7 7 7' : 'M19 9l-7 7-7-7'} size={10} />
          </button>
          {chOpen && (
            <>
              {aiConfig?.whatsapp_enabled && (
                <button
                  onClick={() => toggleChannelFilter('whatsapp')}
                  className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs transition-colors ${
                    channelFilter === 'whatsapp'
                      ? 'bg-emerald-500/10 text-emerald-400'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'
                  }`}>
                  <WaIcon size={13} />
                  <span className="truncate">{aiConfig.whatsapp_phone_id || 'واتساب'}</span>
                </button>
              )}
              {aiConfig?.instagram_enabled && (
                <button
                  onClick={() => toggleChannelFilter('instagram')}
                  className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs transition-colors ${
                    channelFilter === 'instagram'
                      ? 'bg-pink-500/10 text-pink-400'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'
                  }`}>
                  <IgIcon size={13} />
                  <span className="truncate">{aiConfig.ig_username || 'إنستقرام'}</span>
                </button>
              )}
              <button
                onClick={() => toggleChannelFilter('widget')}
                className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs transition-colors ${
                  channelFilter === 'widget'
                    ? 'bg-indigo-500/10 text-indigo-400'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'
                }`}>
                <Icon paths="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"
                      size={13} className={channelFilter === 'widget' ? 'text-indigo-400' : 'text-indigo-400/50'} />
                <span>ويدجت</span>
              </button>
              {channelFilter && (
                <button
                  onClick={() => setChannelFilter(null)}
                  className="flex items-center gap-1 px-3 py-1 text-[10px] text-slate-600 hover:text-red-400 transition-colors">
                  <Icon paths={['M18 6L6 18', 'M6 6l12 12']} size={9} />
                  <span>إلغاء الفلتر</span>
                </button>
              )}
            </>
          )}
        </div>

      </nav>

      {/* ══════════════════════ CONVERSATION LIST ══════════════════════ */}
      <aside className="w-80 shrink-0 bg-content1 border-l border-divider flex flex-col">

        {/* Top bar: search */}
        <div className="px-3 py-2 border-b border-divider flex items-center gap-2 flex-shrink-0">
          <button
            onClick={() => setNavCollapsed(o => !o)}
            className={`p-0.5 flex-shrink-0 transition-colors ${navCollapsed ? 'text-indigo-400' : 'text-slate-500 hover:text-slate-300'}`}
            title={navCollapsed ? 'إظهار الشريط الجانبي' : 'إخفاء الشريط الجانبي'}
          >
            <Icon paths={['M4 6h16', 'M4 12h16', 'M4 18h16']} size={15} />
          </button>
          <div className="flex-1 min-w-0">
            <Input
              placeholder="البحث في المحادثات..."
              value={search}
              onValueChange={setSearch}
              variant="flat"
              size="sm"
              classNames={{
                inputWrapper: 'bg-content2 h-8 min-h-8 shadow-none',
                input: 'text-xs text-foreground placeholder:text-slate-500',
              }}
              startContent={
                <Icon paths={['M21 21l-4.35-4.35', 'M11 19a8 8 0 100-16 8 8 0 000 16z']}
                      size={11} className="text-slate-500 flex-shrink-0" />
              }
            />
          </div>
          <button
            onClick={() => navigate(`/store/${storeId}/contacts`)}
            className="text-slate-500 hover:text-slate-300 p-0.5 flex-shrink-0 transition-colors"
            title="جهات الاتصال"
          >
            <Icon paths="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" size={15} />
          </button>
        </div>

        {/* Header + filters */}
        <div className="px-4 pt-3 flex-shrink-0">
          <div className="flex items-center justify-between mb-2.5">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-bold text-foreground">المحادثات</h2>
              <span className="text-[10px] font-semibold bg-blue-500/15 text-blue-400 px-1.5 py-0.5 rounded">مفتوحة</span>
            </div>
            <button
              onClick={loadConversations}
              className="text-slate-500 hover:text-slate-300 p-1 rounded-md hover:bg-content2"
              title="تحديث"
            >
              <Icon paths="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" size={12} />
            </button>
          </div>

          {/* Status + Sort dropdowns */}
          <div className="flex gap-2 mb-3">
            {/* Status — functional dropdown */}
            <div className="flex-1 relative" ref={statusMenuRef}>
              <button
                onClick={() => setShowStatusMenu(o => !o)}
                className={`w-full text-xs border rounded-lg px-2.5 py-1.5 flex items-center justify-between transition-colors ${
                  showStatusMenu
                    ? 'border-indigo-500 text-indigo-300 bg-content2'
                    : statusFilter !== 'open'
                    ? 'border-indigo-500/50 text-indigo-300 bg-content2'
                    : 'border-divider text-slate-300 bg-content2 hover:border-slate-500'
                }`}>
                <span>{statusLabels[statusFilter]}</span>
                <Icon paths={showStatusMenu ? 'M5 15l7-7 7 7' : 'M19 9l-7 7-7-7'} size={10} className="text-slate-500" />
              </button>
              {showStatusMenu && (
                <div className="absolute top-full right-0 mt-1 bg-content1 border border-divider rounded-xl shadow-xl z-50 min-w-[130px] overflow-hidden">
                  {(Object.entries(statusLabels) as [StatusFilter, string][]).map(([val, label]) => (
                    <button key={val}
                      onClick={() => { setStatusFilter(val); setShowStatusMenu(false) }}
                      className={`w-full text-right px-3 py-2 text-xs flex items-center gap-2 transition-colors ${
                        statusFilter === val
                          ? 'bg-indigo-500/10 text-indigo-400'
                          : 'text-slate-400 hover:bg-content2 hover:text-slate-200'
                      }`}>
                      {statusFilter === val && <Icon paths="M5 13l4 4L19 7" size={11} className="text-indigo-400 flex-shrink-0" />}
                      {statusFilter !== val && <span className="w-[11px] flex-shrink-0" />}
                      {label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Sort — functional dropdown */}
            <div className="flex-1 relative" ref={sortMenuRef}>
              <button
                onClick={() => setShowSortMenu(o => !o)}
                className={`w-full text-xs border rounded-lg px-2.5 py-1.5 flex items-center justify-between transition-colors ${
                  showSortMenu
                    ? 'border-indigo-500 text-indigo-300 bg-content2'
                    : 'border-divider text-slate-300 bg-content2 hover:border-slate-500'
                }`}>
                <span>{sortLabels[sortOrder]}</span>
                <Icon paths={showSortMenu ? 'M5 15l7-7 7 7' : 'M19 9l-7 7-7-7'} size={10} className="text-slate-500" />
              </button>
              {showSortMenu && (
                <div className="absolute top-full right-0 mt-1 bg-content1 border border-divider rounded-xl shadow-xl z-50 min-w-[130px] overflow-hidden">
                  {(Object.entries(sortLabels) as [SortOrder, string][]).map(([val, label]) => (
                    <button key={val}
                      onClick={() => { setSortOrder(val); setShowSortMenu(false) }}
                      className={`w-full text-right px-3 py-2 text-xs flex items-center gap-2 transition-colors ${
                        sortOrder === val
                          ? 'bg-indigo-500/10 text-indigo-400'
                          : 'text-slate-400 hover:bg-content2 hover:text-slate-200'
                      }`}>
                      {sortOrder === val && <Icon paths="M5 13l4 4L19 7" size={11} className="text-indigo-400 flex-shrink-0" />}
                      {sortOrder !== val && <span className="w-[11px] flex-shrink-0" />}
                      {label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Tabs: Mine | Unassigned | All */}
          <div className="flex -mx-4 border-b border-divider">
            {([
              { id: 'mine'       as ActiveTab, label: 'لي',         count: mineCount },
              { id: 'unassigned' as ActiveTab, label: 'غير مُعيَّن', count: unassignedCount },
              { id: 'all'        as ActiveTab, label: 'الكل',        count: total },
            ]).map(tab => {
              const isActive = activeTab === tab.id && viewMode === 'all' && !channelFilter && empFilter === null
              return (
                <button
                  key={tab.id}
                  onClick={() => { setActiveTab(tab.id); setViewMode('all'); setChannelFilter(null); setEmpFilter(null) }}
                  className={`flex-1 py-2 text-[11px] font-medium relative flex items-center justify-center gap-1.5 transition-colors ${
                    isActive ? 'text-indigo-400' : 'text-slate-500 hover:text-slate-300'
                  }`}
                >
                  <span>{tab.label}</span>
                  {tab.count > 0 && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-bold ${
                      isActive ? 'bg-indigo-500 text-white' : 'bg-slate-700/60 text-slate-400'
                    }`}>
                      {tab.count}
                    </span>
                  )}
                  {isActive && <span className="absolute bottom-0 left-3 right-3 h-0.5 bg-indigo-500 rounded-full" />}
                </button>
              )
            })}
          </div>
        </div>

        {/* Active filter chips */}
        {(channelFilter || empFilter !== null) && (
          <div className="px-4 py-1.5 flex gap-1.5 flex-wrap border-b border-divider/40">
            {channelFilter && (
              <span className="flex items-center gap-1 text-[10px] bg-indigo-500/15 text-indigo-400 px-2 py-0.5 rounded-full">
                {channelFilter === 'whatsapp' ? <WaIcon size={9} /> : channelFilter === 'instagram' ? <IgIcon size={9} /> :
                  <Icon paths="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" size={9} className="text-indigo-400" />}
                {channelLabel(channelFilter)}
                <button onClick={() => setChannelFilter(null)} className="hover:text-white ml-0.5">✕</button>
              </span>
            )}
            {empFilter !== null && (
              <span className="flex items-center gap-1 text-[10px] bg-indigo-500/15 text-indigo-400 px-2 py-0.5 rounded-full">
                {employees.find(e => e.id === empFilter)?.name || 'موظف'}
                <button onClick={() => setEmpFilter(null)} className="hover:text-white ml-0.5">✕</button>
              </span>
            )}
          </div>
        )}

        {/* Conversation list items */}
        <div className="flex-1 overflow-y-auto" ref={assignRef}>
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Spinner size="sm" color="primary" />
            </div>
          ) : viewMode === 'mentions' ? (
            <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
              <div className="w-12 h-12 rounded-2xl bg-content2 flex items-center justify-center mb-3">
                <Icon paths="M16 12a4 4 0 10-8 0 4 4 0 008 0zm0 0v1.5a2.5 2.5 0 005 0V12a9 9 0 10-9 9m4.5-1.206a8.959 8.959 0 01-4.5 1.207"
                      size={22} className="text-slate-600" />
              </div>
              <p className="text-sm text-slate-400 font-semibold">المذكورات قريباً</p>
              <p className="text-xs text-slate-600 mt-1">سيتم إضافة هذه الميزة في تحديث قادم</p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
              <div className="w-12 h-12 rounded-2xl bg-content2 flex items-center justify-center mb-3">
                <Icon paths="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                      size={22} className="text-slate-600" />
              </div>
              <p className="text-sm text-slate-400 font-semibold">لا توجد محادثات</p>
              <p className="text-xs text-slate-600 mt-1">جرّب تغيير الفلتر</p>
            </div>
          ) : (
            <div>
              {filtered.map(c => {
                const isActive = selectedId === c.session_id
                const ch = detectChannel(c)
                const lastMsg = c.last_message
                const isAssigning = assigningId === c.session_id
                return (
                  <div key={c.session_id} className="relative">
                    <button
                      onClick={() => openConversation(c)}
                      className={`w-full text-right px-4 py-3 border-b border-divider/40 transition-colors group
                        ${isActive
                          ? 'bg-indigo-500/10 border-r-2 border-r-indigo-500'
                          : c.unread
                          ? 'bg-blue-500/5 hover:bg-content2'
                          : 'hover:bg-content2'
                        }
                      `}
                    >
                      {/* Line 1: channel icon + label */}
                      <div className="flex items-center gap-1.5 mb-1">
                        {ch === 'whatsapp'  ? <WaIcon size={11} /> :
                         ch === 'instagram' ? <IgIcon size={11} /> : (
                          <Icon paths="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"
                                size={11} className="text-indigo-400 flex-shrink-0" />
                        )}
                        <span className="text-[10px] text-slate-500">{channelLabel(ch)}</span>
                      </div>

                      {/* Line 2: name + unread badge + time + assign btn */}
                      <div className="flex items-center gap-1.5 mb-1">
                        <span className="text-xs font-bold text-foreground truncate flex-1">
                          {customerDisplayName(c)}
                        </span>
                        {c.unread && (
                          <span className="w-[18px] h-[18px] bg-blue-500 text-white rounded-full text-[9px] flex items-center justify-center font-bold flex-shrink-0">
                            {(c.user_messages_count && c.user_messages_count > 0) ? c.user_messages_count : '●'}
                          </span>
                        )}
                        <span className="text-[10px] text-slate-500 flex-shrink-0">{relTime(c.last_activity)}</span>
                        <button
                          onClick={e => { e.stopPropagation(); setAssigningId(isAssigning ? null : c.session_id) }}
                          className={`flex-shrink-0 transition-all ${
                            isAssigning
                              ? 'text-indigo-400'
                              : 'opacity-0 group-hover:opacity-100 text-slate-500 hover:text-slate-300'
                          }`}
                          title="تعيين موظف"
                        >
                          <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                            <path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2" />
                            <circle cx="9" cy="7" r="4" />
                            <line x1="19" y1="8" x2="19" y2="14" />
                            <line x1="22" y1="11" x2="16" y2="11" />
                          </svg>
                        </button>
                      </div>

                      {/* Line 3: last message preview */}
                      <p className="text-[11px] text-slate-500 truncate leading-relaxed">
                        {lastMsg?.content
                          ? lastMsg.content.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
                          : 'لا توجد رسائل'}
                      </p>
                    </button>

                    {/* Assign employee dropdown */}
                    {isAssigning && (
                      <div className="absolute left-0 top-full mt-0 bg-content1 border border-divider rounded-xl shadow-2xl z-50 min-w-[160px] overflow-hidden"
                           onClick={e => e.stopPropagation()}>
                        <p className="px-3 py-1.5 text-[10px] text-slate-500 border-b border-divider font-semibold">تعيين إلى</p>
                        {employees.length === 0 ? (
                          <p className="px-3 py-2 text-[11px] text-slate-600">لا يوجد موظفون</p>
                        ) : employees.map(emp => (
                          <button key={emp.id}
                            onClick={() => { setAssigningId(null) }}
                            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-slate-400 hover:bg-content2 hover:text-slate-200 transition-colors">
                            <div className="w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-400 flex items-center justify-center text-[10px] font-bold flex-shrink-0">
                              {emp.name.charAt(0)}
                            </div>
                            <span>{emp.name}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </aside>

      {/* ══════════════════════ CHAT PANEL ══════════════════════ */}
      <main className="flex-1 flex flex-col bg-content2 min-w-0">
        {!selected ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center px-6">
            <div className="w-20 h-20 rounded-3xl bg-content1 border border-divider flex items-center justify-center mb-4">
              <Icon paths="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                    size={36} className="text-slate-600" />
            </div>
            <p className="text-base font-semibold text-slate-400">اختر محادثة لعرضها</p>
            <p className="text-xs text-slate-600 mt-1">اضغط على أي محادثة من القائمة</p>
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
                    name={customerDisplayName(selected)[0]}
                    size="sm"
                    className={selected.bot_enabled
                      ? 'bg-gradient-to-br from-teal-500 to-cyan-600 text-white'
                      : 'bg-gradient-to-br from-amber-500 to-orange-600 text-white'}
                  />
                  <div className="min-w-0">
                    <p className="text-sm font-bold text-foreground truncate">{customerDisplayName(selected)}</p>
                    <div className="flex items-center gap-2 text-xs">
                      <span className={`flex items-center gap-1 ${selected.bot_enabled ? 'text-blue-400' : 'text-amber-400'}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${selected.bot_enabled ? 'bg-blue-400' : 'bg-amber-400'}`} />
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
                    <Button size="sm" color="warning" variant="flat" onPress={handleTakeover}
                      startContent={<Icon paths="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" size={13} />}>
                      تولي المحادثة
                    </Button>
                  ) : (
                    <Button size="sm" color="success" variant="flat" onPress={handleHandback}
                      startContent={<Icon paths="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" size={13} />}>
                      إعادة للبوت
                    </Button>
                  )}
                  {!selected.bot_enabled && (
                    <Button size="sm" variant="flat" onPress={openEndModal}
                      startContent={<Icon paths={['M5 13l4 4L19 7']} size={13} />}
                      className="bg-teal-500/15 text-teal-500 hover:bg-teal-500/25">
                      إنهاء + تقييم
                    </Button>
                  )}
                </div>
              </div>
            </header>

            {/* Action error */}
            {actionError && (
              <div className="px-5 py-2.5 bg-danger/10 border-b border-danger/20 text-danger text-xs font-bold flex items-center justify-between gap-3">
                <span className="flex items-center gap-2">
                  <Icon paths="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" size={14} />
                  {actionError}
                </span>
                <button onClick={() => setActionError('')} className="text-danger/70 hover:text-danger">
                  <Icon paths={['M18 6L6 18', 'M6 6l12 12']} size={14} />
                </button>
              </div>
            )}

            {/* Messages */}
            <div ref={messagesRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
              {selected.messages?.length === 0 ? (
                <div className="flex items-center justify-center py-12">
                  <p className="text-sm text-slate-500">لا توجد رسائل بعد</p>
                </div>
              ) : selected.messages?.map((msg: Message, i: number) => {
                const isUser  = msg.role === 'user'
                const isAdmin = msg.role === 'admin'
                const isCsat  = msg.meta?.kind === 'csat'
                const empName = msg.employee_name
                return (
                  <div key={i} className={`flex gap-2 ${isUser ? 'justify-start' : 'justify-end'}`}>
                    {!isUser && (
                      <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${
                        isAdmin ? 'bg-amber-500/20 text-amber-400'
                        : isCsat ? 'bg-teal-500/20 text-teal-400'
                        : 'bg-blue-500/20 text-blue-400'
                      }`}>
                        {isAdmin ? (empName ? empName.trim().charAt(0) : '👨‍💼') : isCsat ? '⭐' : '🤖'}
                      </div>
                    )}
                    <div className={`
                      max-w-[70%] min-w-[80px] rounded-2xl px-4 py-2.5 text-sm leading-relaxed
                      ${isUser  ? 'bg-gradient-to-br from-teal-600 to-cyan-700 text-white rounded-tr-sm'
                      : isAdmin ? 'bg-amber-50 text-amber-900 border border-amber-200 rounded-tl-sm'
                      : isCsat  ? 'bg-teal-500/10 text-teal-900 border border-teal-500/30 rounded-tl-sm'
                      : 'bg-content1 text-foreground border border-divider rounded-tl-sm'}
                    `}>
                      {isAdmin && <p className="text-[10px] text-amber-600 mb-1 font-bold">{empName ? `${empName} · موظف` : 'الإدارة'}</p>}
                      {isCsat  && <p className="text-[10px] text-teal-600 mb-1 font-bold">استطلاع رضا</p>}
                      <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{renderMessageBody(msg.content)}</div>
                      {isCsat && msg.meta?.options && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          {msg.meta.options.map(opt => (
                            <span key={opt.value} className="text-[11px] px-2 py-1 rounded-full bg-white/70 border border-teal-500/30 text-teal-700">
                              {opt.label}
                            </span>
                          ))}
                        </div>
                      )}
                      <p className={`text-[10px] mt-1 ${isUser ? 'text-white/70' : 'text-slate-500'}`}>{fmtTime(msg.ts)}</p>
                    </div>
                    {isUser && (
                      <div className="w-7 h-7 rounded-full bg-blue-500/20 text-blue-400 flex items-center justify-center text-xs font-bold flex-shrink-0">
                        👤
                      </div>
                    )}
                  </div>
                )
              })}
            </div>

            {/* Reply input */}
            {!selected.bot_enabled && (
              <footer className="px-4 py-3 border-t border-divider bg-content1 flex-shrink-0">
                <div className="flex gap-2">
                  <Textarea
                    placeholder="اكتب ردك كأدمن..."
                    value={replyText} onValueChange={setReplyText}
                    variant="bordered" minRows={1} maxRows={4}
                    classNames={{ inputWrapper: 'border-divider bg-content2', input: 'text-sm' }}
                    onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendReply() } }}
                  />
                  <Button color="primary" isLoading={sending} isIconOnly onPress={sendReply}
                    isDisabled={!replyText.trim()}
                    className="self-end h-10 w-10 min-w-10 bg-gradient-to-br from-teal-600 to-cyan-700">
                    <Icon paths={['M22 2L11 13', 'M22 2l-7 20-4-9-9-4 20-7z']} size={15} />
                  </Button>
                </div>
                <p className="text-[10px] text-slate-600 mt-1.5 px-1">Enter للإرسال · Shift+Enter لسطر جديد</p>
              </footer>
            )}

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

      {/* ══════════════════════ END-CONVERSATION MODAL ══════════════════════ */}
      <Modal isOpen={endOpen} onOpenChange={setEndOpen} placement="center" backdrop="blur" size="md">
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
                <Textarea label="رسالة الوداع" value={farewell} onValueChange={setFarewell}
                  variant="bordered" minRows={3} maxRows={6} />
                <label className="flex items-center gap-2 text-xs text-slate-500 cursor-pointer">
                  <input type="checkbox" checked={skipCsat} onChange={e => setSkipCsat(e.target.checked)} />
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
                <Button color="primary" isLoading={endingChat} onPress={confirmEndChat}
                  className="bg-gradient-to-br from-teal-600 to-cyan-700 text-white font-bold"
                  startContent={<Icon paths={['M5 13l4 4L19 7']} size={13} />}>
                  إنهاء وإرسال
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>

      {/* ══════════════════════ ACCESS-REASON MODAL ══════════════════════ */}
      <Modal
        isOpen={reasonModalOpen}
        onOpenChange={(open) => {
          setReasonModalOpen(open)
          if (!open && reasonResolverRef.current) { reasonResolverRef.current(null); reasonResolverRef.current = null }
        }}
        placement="center" backdrop="blur" size="md" isDismissable={false}
      >
        <ModalContent>
          {(close) => (
            <>
              <ModalHeader className="flex flex-col gap-1" dir="rtl">
                <span className="text-base font-bold">سبب فتح المحادثة</span>
                <span className="text-xs text-slate-500 font-normal">
                  لأنك تفتح محادثات متجر آخر، نسجّل سبب الوصول مع الوقت في سجل المراجعة.
                </span>
              </ModalHeader>
              <ModalBody dir="rtl">
                <Textarea autoFocus label="السبب" placeholder="مثلاً: متابعة بلاغ #4221 — دعم فني"
                  value={reasonDraft} onValueChange={setReasonDraft}
                  variant="bordered" minRows={2} maxRows={5}
                  description="مطلوب 5 أحرف على الأقل." />
              </ModalBody>
              <ModalFooter>
                <Button variant="light" onPress={() => {
                  reasonResolverRef.current?.(null); reasonResolverRef.current = null
                  setReasonModalOpen(false); close()
                }}>إلغاء</Button>
                <Button color="primary" isDisabled={reasonDraft.trim().length < 5}
                  onPress={() => {
                    const r = reasonDraft.trim()
                    reasonResolverRef.current?.(r); reasonResolverRef.current = null
                    setReasonModalOpen(false); close()
                  }}>
                  تأكيد وفتح
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>

    </div>
  )
}
