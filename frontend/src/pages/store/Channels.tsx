import { useEffect, useState } from 'react'
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader, Input, Spinner, Chip } from '@heroui/react'
import { api, ChannelData } from '../../api'

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

/* ── Logos (simple brand-tile style, matching the Integrations page) ── */
function Tile({ color, label, size = 36, fontSize = 13 }: {
  color: string; label: string; size?: number; fontSize?: number
}) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none">
      <rect width={40} height={40} rx={10} fill={color} />
      <text x="50%" y="54%" dominantBaseline="middle" textAnchor="middle"
        fill="white" fontWeight="bold" fontSize={fontSize} fontFamily="system-ui">{label}</text>
    </svg>
  )
}
const TelegramLogo  = ({ size = 36 }: { size?: number }) => <Tile color="#229ED9" label="✈" size={size} fontSize={16} />
const TikTokLogo    = ({ size = 36 }: { size?: number }) => <Tile color="#010101" label="TT"  size={size} fontSize={13} />
const MessengerLogo = ({ size = 36 }: { size?: number }) => <Tile color="#0084FF" label="m"   size={size} fontSize={18} />
const InstagramLogo = ({ size = 36 }: { size?: number }) => <Tile color="#C13584" label="ig"  size={size} fontSize={13} />
const XLogo         = ({ size = 36 }: { size?: number }) => <Tile color="#111827" label="X"   size={size} fontSize={16} />
const SnapLogo      = ({ size = 36 }: { size?: number }) => <Tile color="#FFFC00" label="👻"  size={size} fontSize={14} />
const DiscordLogo   = ({ size = 36 }: { size?: number }) => <Tile color="#5865F2" label="D"   size={size} fontSize={15} />

/* ── Types ── */
type Status = 'connected' | 'disconnected' | 'coming_soon'

interface ChannelDef {
  id:          string
  name:        string
  nameEn?:     string
  description: string
  logo:        React.ReactNode
  category:    'messaging' | 'social'
  comingSoon?: boolean
  manageable?: boolean   // connect/toggle/disconnect wired in THIS tab (Telegram only for now)
  // filled from API at runtime:
  status:      Status
  data?:       ChannelData
}

const CHANNELS_DEF: Omit<ChannelDef, 'status' | 'data'>[] = [
  { id: 'telegram',  name: 'تيليجرام',  nameEn: 'Telegram',  category: 'messaging', logo: <TelegramLogo />,  manageable: true, description: 'اربط بوت تيليجرام وسيرد المساعد الذكي على رسائل عملائك تلقائياً.' },
  { id: 'messenger', name: 'ماسنجر',    nameEn: 'Messenger', category: 'messaging', logo: <MessengerLogo />, description: 'محادثات صفحة فيسبوك يرد عليها البوت تلقائياً.', comingSoon: true },
  { id: 'instagram', name: 'إنستجرام',  nameEn: 'Instagram', category: 'messaging', logo: <InstagramLogo />, description: 'رسائل الـ Direct على إنستجرام يرد عليها البوت تلقائياً.', comingSoon: true },
  { id: 'tiktok',    name: 'تيك توك',   nameEn: 'TikTok',    category: 'social',    logo: <TikTokLogo />,    description: 'الرد الآلي على رسائل تيك توك للأعمال.', comingSoon: true },
  { id: 'x',         name: 'إكس',       nameEn: 'X',         category: 'social',    logo: <XLogo />,         description: 'الرد على الرسائل المباشرة في منصة X.', comingSoon: true },
  { id: 'snapchat',  name: 'سناب شات',  nameEn: 'Snapchat',  category: 'social',    logo: <SnapLogo />,      description: 'محادثات سناب شات للأعمال.', comingSoon: true },
  { id: 'discord',   name: 'ديسكورد',   nameEn: 'Discord',   category: 'social',    logo: <DiscordLogo />,   description: 'الرد الآلي داخل سيرفر ديسكورد متجرك.', comingSoon: true },
]

/* ── Toast ── */
function Toast({ msg, type }: { msg: string; type: 'success' | 'error' | 'info' }) {
  const colors = { success: 'bg-emerald-500', error: 'bg-red-500', info: 'bg-blue-500' }
  return (
    <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 z-50 ${colors[type]} text-white text-xs font-bold px-5 py-2.5 rounded-full shadow-xl flex items-center gap-2`}>
      {type === 'success' && <Icon paths="M5 13l4 4L19 7" size={13} />}
      {type === 'error'   && <Icon paths={['M18 6L6 18', 'M6 6l12 12']} size={13} />}
      {type === 'info'    && <Icon paths="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" size={13} />}
      {msg}
    </div>
  )
}

/* ── Card ── */
function ChannelCard({ channel, onConnect, onDisconnect, onToggle, busy }: {
  channel:      ChannelDef
  onConnect:    (id: string) => void
  onDisconnect: (id: string) => void
  onToggle:     (id: string, enabled: boolean) => void
  busy?:        boolean
}) {
  const connected  = channel.status === 'connected'
  const comingSoon = channel.comingSoon && !connected
  const enabled    = channel.data?.enabled !== false
  return (
    <div className={`relative bg-content1 border rounded-2xl p-5 flex flex-col gap-4 transition-all
      ${connected ? 'border-emerald-500/30 shadow-[0_0_0_1px_rgba(16,185,129,0.1)]' : 'border-divider hover:border-default-300'}`}>
      {connected && (
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-emerald-500 to-transparent rounded-t-2xl" />
      )}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-shrink-0">{channel.logo}</div>
        {connected ? (
          <Chip size="sm" color={enabled ? 'success' : 'default'} variant="flat"
            startContent={<span className={`w-1.5 h-1.5 rounded-full ${enabled ? 'bg-emerald-500 animate-pulse' : 'bg-default-400'}`} />}
            className="text-[10px] font-bold">{enabled ? 'متصل' : 'متوقف مؤقتاً'}</Chip>
        ) : comingSoon ? (
          <Chip size="sm" color="default" variant="flat" className="text-[10px] font-bold text-slate-500">قريباً</Chip>
        ) : (
          <Chip size="sm" color="default" variant="flat" className="text-[10px]">غير متصل</Chip>
        )}
      </div>
      <div className="flex-1">
        <p className="text-sm font-bold text-foreground mb-1">
          {channel.name}
          {channel.nameEn && <span className="text-[10px] font-normal text-slate-500 mr-1.5">{channel.nameEn}</span>}
        </p>
        <p className="text-xs text-default-500 leading-relaxed">{channel.description}</p>
        {connected && channel.data?.bot_username && (
          <p className="text-[10px] text-emerald-500 mt-1.5 font-mono">@{channel.data.bot_username}</p>
        )}
      </div>
      <div className="flex gap-2">
        {connected && !channel.manageable ? (
          <div className="flex-1 py-2 text-xs font-semibold rounded-xl border border-divider text-default-500 text-center cursor-default">
            يُدار من إعدادات ميتا
          </div>
        ) : comingSoon ? (
          <button disabled className="flex-1 py-2 text-xs font-semibold rounded-xl border border-divider text-slate-500 cursor-not-allowed opacity-60">
            قريباً
          </button>
        ) : connected ? (
          <div className="flex gap-1.5 w-full">
            <button onClick={() => onToggle(channel.id, !enabled)} disabled={busy}
              className="flex-1 py-2 text-xs font-semibold rounded-xl border border-amber-200 text-amber-600 hover:bg-amber-50 transition-colors disabled:opacity-50">
              {enabled ? 'إيقاف مؤقت' : 'تشغيل'}
            </button>
            <button onClick={() => onDisconnect(channel.id)} disabled={busy}
              className="flex-1 py-2 text-xs font-semibold rounded-xl border border-red-200 text-red-500 hover:bg-red-50 transition-colors disabled:opacity-50">
              قطع الاتصال
            </button>
          </div>
        ) : (
          <button onClick={() => onConnect(channel.id)} disabled={busy}
            className="flex-1 py-2 text-xs font-bold rounded-xl bg-primary text-white hover:opacity-90 disabled:opacity-60 transition-opacity flex items-center justify-center gap-2">
            {busy ? <><Spinner size="sm" color="white" /> جارٍ...</> : 'ربط الآن'}
          </button>
        )}
      </div>
    </div>
  )
}

/* ── Telegram connect modal ── */
function TelegramConnectModal({ isOpen, onClose, storeId, onDone, onToast }: {
  isOpen: boolean
  onClose: () => void
  storeId: string
  onDone: () => void
  onToast: (msg: string, type: 'success' | 'error' | 'info') => void
}) {
  const [token, setToken]     = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState('')

  async function connect() {
    const t = token.trim()
    if (!t) return
    setLoading(true); setError('')
    try {
      const res = await api.telegramConnect(storeId, t)
      onToast(`تم ربط بوت تيليجرام @${res.bot_username} 🎉`, 'success')
      setToken('')
      onClose()
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'تعذّر ربط البوت')
    } finally { setLoading(false) }
  }

  return (
    <Modal isOpen={isOpen} onOpenChange={(o) => { if (!o) { setError(''); onClose() } }} placement="center" backdrop="blur" size="md">
      <ModalContent>
        {(close) => (
          <>
            <ModalHeader dir="rtl">
              <div className="flex items-center gap-3">
                <TelegramLogo size={30} />
                <div>
                  <p className="text-sm font-bold">ربط بوت تيليجرام</p>
                  <p className="text-xs font-normal text-default-500">عبر توكن البوت من BotFather</p>
                </div>
              </div>
            </ModalHeader>
            <ModalBody dir="rtl">
              <ol className="text-xs text-default-600 leading-relaxed list-decimal mr-4 space-y-1.5">
                <li>افتح <a href="https://t.me/BotFather" target="_blank" rel="noreferrer" className="text-sky-600 font-semibold hover:underline">@BotFather</a> في تيليجرام وأرسل الأمر <code className="px-1 bg-content2 rounded">/newbot</code>.</li>
                <li>اختر اسماً ومُعرّفاً للبوت، وسيعطيك <span className="font-semibold text-foreground">توكن البوت</span> (Bot Token).</li>
                <li>الصق التوكن بالأسفل ثم اضغط «ربط البوت» — وسيبدأ المساعد بالرد فوراً.</li>
              </ol>
              <Input
                autoFocus
                label="توكن البوت (Bot Token)"
                placeholder="123456789:AAH...xyz"
                value={token}
                onValueChange={v => { setToken(v); setError('') }}
                variant="bordered"
                onKeyDown={e => { if (e.key === 'Enter') connect() }}
                isInvalid={!!error}
                errorMessage={error}
              />
              <div className="bg-content2 rounded-xl p-3 text-[11px] text-default-500 leading-relaxed">
                نحفظ التوكن مشفّراً ونضبط الويبهوك تلقائياً. يمكنك إيقاف الرد الآلي أو قطع الاتصال في أي وقت.
              </div>
            </ModalBody>
            <ModalFooter>
              <button onClick={close} className="px-4 py-2 text-xs text-default-500 hover:text-foreground">إلغاء</button>
              <button onClick={connect} disabled={!token.trim() || loading}
                className="px-5 py-2 text-xs font-bold rounded-xl bg-[#229ED9] text-white hover:opacity-90 disabled:opacity-50 flex items-center gap-2">
                {loading ? <><Spinner size="sm" color="white" /> جارٍ الربط...</> : 'ربط البوت'}
              </button>
            </ModalFooter>
          </>
        )}
      </ModalContent>
    </Modal>
  )
}

/* ══════════════════════════════════ MAIN PAGE ══════════════════════════════════ */
export default function Channels({ storeId }: Props) {
  const [channels, setChannels] = useState<ChannelDef[]>(
    CHANNELS_DEF.map(d => ({ ...d, status: 'disconnected' as Status }))
  )
  const [loading, setLoading] = useState(true)
  const [busy, setBusy]       = useState<string | null>(null)
  const [toast, setToast]     = useState<{ msg: string; type: 'success' | 'error' | 'info' } | null>(null)
  const [tgModal, setTgModal] = useState(false)
  const [disconnectTarget, setDisconnectTarget] = useState<string | null>(null)

  function showToast(msg: string, type: 'success' | 'error' | 'info' = 'info') {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3500)
  }

  useEffect(() => { loadChannels() /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [storeId])

  async function loadChannels() {
    setLoading(true)
    try {
      const res = await api.listChannels(storeId)
      const apiData = res.channels || {}
      setChannels(CHANNELS_DEF.map(def => {
        const d = apiData[def.id]
        const connected = !!d?.connected
        return {
          ...def,
          status: connected ? 'connected'
                : def.comingSoon ? 'coming_soon'
                : 'disconnected',
          data: d,
        } as ChannelDef
      }))
    } catch {
      setChannels(CHANNELS_DEF.map(d => ({
        ...d, status: (d.comingSoon ? 'coming_soon' : 'disconnected') as Status,
      })))
    } finally { setLoading(false) }
  }

  function handleConnect(id: string) {
    if (id === 'telegram') setTgModal(true)
    else showToast('هذه القناة قيد التطوير وستُتاح قريباً', 'info')
  }

  async function handleToggle(id: string, enabled: boolean) {
    if (id !== 'telegram') return
    setBusy(id)
    try {
      await api.telegramToggle(storeId, enabled)
      showToast(enabled ? 'تم تشغيل الرد الآلي' : 'تم إيقاف الرد الآلي مؤقتاً', 'success')
      await loadChannels()
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'تعذّر تغيير الحالة', 'error')
    } finally { setBusy(null) }
  }

  async function confirmDisconnect() {
    if (disconnectTarget !== 'telegram') { setDisconnectTarget(null); return }
    setBusy('telegram')
    try {
      await api.telegramDisconnect(storeId)
      showToast('تم قطع الاتصال مع تيليجرام', 'success')
      await loadChannels()
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'تعذّر قطع الاتصال', 'error')
    } finally { setBusy(null); setDisconnectTarget(null) }
  }

  const categories = [
    { id: 'messaging' as const, label: 'قنوات المراسلة',
      icon: 'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z',
      color: 'text-sky-400', bg: 'bg-sky-500/10' },
    { id: 'social' as const, label: 'منصات التواصل',
      icon: 'M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z',
      color: 'text-fuchsia-400', bg: 'bg-fuchsia-500/10' },
  ]

  const connectedCount = channels.filter(c => c.status === 'connected').length

  return (
    <div className="min-h-screen bg-background p-6" dir="rtl">
      <div className="max-w-5xl mx-auto">

        {/* Header */}
        <div className="flex items-start justify-between gap-4 mb-8">
          <div>
            <h1 className="text-2xl font-extrabold text-foreground mb-1">القنوات</h1>
            <p className="text-sm text-default-500">اربط منصات المراسلة ليرد المساعد الذكي على عملائك تلقائياً</p>
          </div>
          <div className="flex items-center gap-2 px-4 py-2.5 bg-content1 border border-divider rounded-2xl flex-shrink-0">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-xs font-bold text-foreground">{connectedCount}</span>
            <span className="text-xs text-default-500">متصل</span>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-24">
            <Spinner size="lg" color="primary" />
          </div>
        ) : (
          <>
            {categories.map(cat => {
              const items = channels.filter(c => c.category === cat.id)
              return (
                <section key={cat.id} className="mb-10">
                  <div className="flex items-center gap-2.5 mb-4">
                    <div className={`w-7 h-7 rounded-xl ${cat.bg} flex items-center justify-center flex-shrink-0`}>
                      <Icon paths={cat.icon} size={14} className={cat.color} />
                    </div>
                    <h2 className="text-sm font-bold text-foreground">{cat.label}</h2>
                    <div className="flex-1 h-px bg-divider" />
                    <span className="text-[10px] text-default-400">
                      {items.filter(i => i.status === 'connected').length} / {items.length} متصل
                    </span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                    {items.map(channel => (
                      <ChannelCard
                        key={channel.id}
                        channel={channel}
                        onConnect={handleConnect}
                        onDisconnect={(id) => setDisconnectTarget(id)}
                        onToggle={handleToggle}
                        busy={busy === channel.id}
                      />
                    ))}
                  </div>
                </section>
              )
            })}

            {/* Request new */}
            <div className="mt-4 border-2 border-dashed border-divider rounded-2xl p-8 text-center">
              <div className="w-12 h-12 mx-auto rounded-2xl bg-content2 flex items-center justify-center mb-3">
                <Icon paths={['M12 5v14', 'M5 12h14']} size={20} className="text-slate-500" />
              </div>
              <p className="text-sm font-bold text-foreground mb-1">تريد قناة أخرى؟</p>
              <p className="text-xs text-default-500 mb-4">أخبرنا وسنضيفها في التحديثات القادمة</p>
              <a href="mailto:support@7ayak.app?subject=طلب قناة جديدة"
                className="inline-flex items-center gap-2 px-4 py-2 bg-content2 border border-divider rounded-xl text-xs font-semibold text-foreground hover:border-default-300 transition-colors">
                <Icon paths="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" size={13} />
                اقتراح قناة
              </a>
            </div>
          </>
        )}
      </div>

      {/* ── Telegram connect modal ── */}
      <TelegramConnectModal
        isOpen={tgModal}
        onClose={() => setTgModal(false)}
        storeId={storeId}
        onDone={loadChannels}
        onToast={showToast}
      />

      {/* ── Disconnect confirmation modal ── */}
      <Modal isOpen={!!disconnectTarget} onOpenChange={open => !open && setDisconnectTarget(null)} placement="center" backdrop="blur" size="sm">
        <ModalContent>
          {(close) => (
            <>
              <ModalHeader dir="rtl">
                <p className="text-sm font-bold text-red-500">قطع الاتصال</p>
              </ModalHeader>
              <ModalBody dir="rtl">
                <p className="text-sm text-foreground">
                  هل تريد فعلاً قطع الاتصال مع{' '}
                  <span className="font-bold">{CHANNELS_DEF.find(d => d.id === disconnectTarget)?.name}</span>؟
                </p>
                <p className="text-xs text-default-500">
                  سيتوقف الرد الآلي وتُحذف بيانات الربط. يمكنك إعادة الربط في أي وقت.
                </p>
              </ModalBody>
              <ModalFooter>
                <button onClick={close} className="px-4 py-2 text-xs text-default-500 hover:text-foreground">إلغاء</button>
                <button onClick={confirmDisconnect} disabled={busy === disconnectTarget}
                  className="px-5 py-2 text-xs font-bold rounded-xl bg-red-500 text-white hover:bg-red-600 disabled:opacity-50 flex items-center gap-2">
                  {busy === disconnectTarget ? <Spinner size="sm" color="white" /> : null}
                  قطع الاتصال
                </button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>

      {toast && <Toast msg={toast.msg} type={toast.type} />}
    </div>
  )
}
