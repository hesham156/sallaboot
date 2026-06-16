/**
 * Contacts — unified CRM built from WhatsApp chat users + Salla customers.
 * Mirrors the standard contacts-list UI with search, pagination, and export.
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import {
  Button, Input, Spinner, Chip, Tooltip,
} from '@heroui/react'
import { api, ApiError, Contact } from '../../api'

/* ── helpers ── */
function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return (name[0] || '?').toUpperCase()
}

function avatarColor(phone: string): string {
  const colors = [
    'bg-blue-500', 'bg-violet-500', 'bg-emerald-500', 'bg-teal-500',
    'bg-sky-500', 'bg-pink-500', 'bg-amber-500', 'bg-rose-500',
  ]
  let hash = 0
  for (const c of phone) hash = (hash * 31 + c.charCodeAt(0)) & 0xffffff
  return colors[hash % colors.length]
}

function fmtDate(iso?: string) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('ar-SA', { dateStyle: 'medium' })
}

function Icon({ d, size = 16, className = '' }: { d: string; size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
      className={className}>
      <path d={d} />
    </svg>
  )
}

/* ══════════════════════════════════════════════════════════════════════
   Main page
══════════════════════════════════════════════════════════════════════ */
export default function Contacts({ storeId }: { storeId: string }) {
  const [contacts, setContacts] = useState<Contact[]>([])
  const [total, setTotal]       = useState(0)
  const [pages, setPages]       = useState(1)
  const [page, setPage]         = useState(1)
  const [search, setSearch]     = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState('')
  const [syncing, setSyncing]   = useState(false)
  const [syncMsg, setSyncMsg]   = useState('')
  const searchTimer             = useRef<ReturnType<typeof setTimeout> | null>(null)

  const PER_PAGE = 25

  /* ── Load page ── */
  const load = useCallback(async (p: number, q: string) => {
    setLoading(true); setError('')
    try {
      const res = await api.listContacts(storeId, { page: p, per_page: PER_PAGE, search: q })
      setContacts(res.contacts || [])
      setTotal(res.total || 0)
      setPages(res.pages || 1)
      setPage(res.page || p)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'فشل تحميل جهات الاتصال')
    } finally {
      setLoading(false)
    }
  }, [storeId])

  useEffect(() => { load(1, '') }, [load])

  /* ── Debounced search ── */
  function handleSearchChange(val: string) {
    setSearchInput(val)
    if (searchTimer.current) clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => {
      setSearch(val)
      load(1, val)
    }, 400)
  }

  /* ── Pagination ── */
  function goPage(p: number) {
    if (p < 1 || p > pages) return
    load(p, search)
  }

  /* ── Sync ── */
  async function handleSync() {
    setSyncing(true); setSyncMsg('')
    try {
      const res = await api.syncContacts(storeId)
      setSyncMsg(res.message)
      await load(1, search)
    } catch (e) {
      setSyncMsg(e instanceof ApiError ? e.message : 'فشل المزامنة')
    } finally {
      setSyncing(false)
    }
  }

  /* ── Export ── */
  function handleExport() {
    const url = api.exportContactsUrl(storeId, search)
    window.open(url, '_blank')
  }

  const start = (page - 1) * PER_PAGE + 1
  const end   = Math.min(page * PER_PAGE, total)

  return (
    <div className="flex flex-col h-full" dir="rtl">
      {/* ── Header bar ── */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-divider bg-background">
        <h1 className="text-xl font-bold text-foreground flex-1">جهات الاتصال</h1>

        <Button size="sm" variant="bordered" isLoading={syncing}
          onPress={handleSync}
          startContent={!syncing && <Icon d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" size={14} />}>
          مزامنة
        </Button>

        <Button size="sm" variant="bordered"
          onPress={handleExport}
          startContent={<Icon d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" size={14} />}>
          تصدير
        </Button>
      </div>

      {/* ── Sync feedback ── */}
      {syncMsg && (
        <div className={`mx-5 mt-3 px-4 py-2.5 rounded-xl text-sm border ${
          syncMsg.includes('فشل')
            ? 'bg-danger-50 border-danger-200 text-danger'
            : 'bg-success-50 border-success-200 text-success-700'
        }`}>
          {syncMsg}
        </div>
      )}

      {/* ── Toolbar: search + stats ── */}
      <div className="flex items-center gap-3 px-5 py-3 border-b border-divider">
        <div className="flex-1 max-w-sm">
          <Input
            size="sm"
            placeholder="بحث عن جهة اتصال..."
            value={searchInput}
            onValueChange={handleSearchChange}
            startContent={<Icon d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0" size={14} className="text-default-400" />}
            isClearable
            onClear={() => { setSearchInput(''); setSearch(''); load(1, '') }}
          />
        </div>
        {!loading && (
          <span className="text-sm text-default-500 whitespace-nowrap">
            النتائج: <b className="text-foreground">{total > 0 ? `${start}–${end}` : '0'}</b> من <b className="text-foreground">{total.toLocaleString('ar-SA')}</b>
          </span>
        )}
      </div>

      {/* ── Error ── */}
      {error && (
        <div className="mx-5 mt-3 p-3 rounded-xl bg-danger-50 border border-danger-200 text-danger text-sm">
          {error}
        </div>
      )}

      {/* ── Table ── */}
      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Spinner size="lg" color="primary" label="جاري التحميل..." />
          </div>
        ) : contacts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center px-6">
            <div className="w-16 h-16 rounded-2xl bg-content2 flex items-center justify-center mx-auto mb-4">
              <Icon d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" size={28} className="text-default-300" />
            </div>
            <p className="text-default-500 font-semibold">لا توجد جهات اتصال</p>
            <p className="text-default-400 text-sm mt-1 max-w-xs">
              {search ? 'لا يوجد نتائج لبحثك' : 'اضغط "مزامنة" لاستيراد جهات الاتصال من الشات وسلة'}
            </p>
            {!search && (
              <Button color="primary" size="sm" className="mt-4" isLoading={syncing} onPress={handleSync}>
                مزامنة الآن
              </Button>
            )}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-divider bg-content1">
                <th className="px-4 py-3 text-right font-medium text-default-500 w-8">
                  {/* checkbox col */}
                </th>
                <th className="px-4 py-3 text-right font-medium text-default-500 min-w-[180px]">الاسم</th>
                <th className="px-4 py-3 text-right font-medium text-default-500 min-w-[200px]">البريد الإلكتروني</th>
                <th className="px-4 py-3 text-right font-medium text-default-500 min-w-[150px]">رقم الهاتف</th>
                <th className="px-4 py-3 text-right font-medium text-default-500 min-w-[140px]">الشركة</th>
                <th className="px-4 py-3 text-right font-medium text-default-500 min-w-[120px]">المدينة</th>
                <th className="px-4 py-3 text-right font-medium text-default-500 min-w-[100px]">الدولة</th>
                <th className="px-4 py-3 text-right font-medium text-default-500 min-w-[90px]">المصدر</th>
              </tr>
            </thead>
            <tbody>
              {contacts.map((c, i) => (
                <tr key={c.id}
                  className={`border-b border-divider transition-colors hover:bg-content2/60
                    ${i % 2 === 0 ? '' : 'bg-content1/40'}`}>
                  {/* Checkbox placeholder */}
                  <td className="px-4 py-3">
                    <div className="w-4 h-4 rounded border border-divider" />
                  </td>

                  {/* Name + avatar */}
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className={`w-9 h-9 rounded-full ${avatarColor(c.phone)} text-white text-xs font-bold flex items-center justify-center flex-shrink-0`}>
                        {c.name ? initials(c.name) : <Icon d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" size={14} />}
                      </div>
                      <div className="min-w-0">
                        <p className="font-medium text-foreground truncate">
                          {c.name || <span className="text-default-400 italic">بدون اسم</span>}
                        </p>
                        {c.last_seen && (
                          <p className="text-[11px] text-default-400">آخر نشاط: {fmtDate(c.last_seen)}</p>
                        )}
                      </div>
                    </div>
                  </td>

                  {/* Email */}
                  <td className="px-4 py-3">
                    {c.email ? (
                      <a href={`mailto:${c.email}`}
                        className="text-primary hover:underline truncate block max-w-[180px]">
                        {c.email}
                      </a>
                    ) : (
                      <span className="text-default-300">—</span>
                    )}
                  </td>

                  {/* Phone */}
                  <td className="px-4 py-3">
                    <span className="font-mono text-foreground">{c.phone}</span>
                  </td>

                  {/* Company */}
                  <td className="px-4 py-3 text-default-600">
                    {c.company || <span className="text-default-300">—</span>}
                  </td>

                  {/* City */}
                  <td className="px-4 py-3 text-default-600">
                    {c.city || <span className="text-default-300">—</span>}
                  </td>

                  {/* Country */}
                  <td className="px-4 py-3 text-default-600">
                    {c.country || <span className="text-default-300">—</span>}
                  </td>

                  {/* Source badge */}
                  <td className="px-4 py-3">
                    <Chip size="sm"
                      color={c.source === 'salla' ? 'success' : 'primary'}
                      variant="flat">
                      {c.source === 'salla' ? 'سلة' : 'شات'}
                    </Chip>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Pagination ── */}
      {!loading && total > PER_PAGE && (
        <div className="flex items-center justify-between px-5 py-3 border-t border-divider bg-background">
          <div className="flex items-center gap-2">
            <Button size="sm" variant="flat" isDisabled={page <= 1}
              onPress={() => goPage(page - 1)}>
              <Icon d="M15 19l-7-7 7-7" size={14} />
            </Button>

            {/* Page numbers */}
            <div className="flex items-center gap-1">
              {Array.from({ length: Math.min(pages, 7) }, (_, i) => {
                let p = i + 1
                if (pages > 7) {
                  if (page <= 4)         p = i + 1
                  else if (page >= pages - 3) p = pages - 6 + i
                  else                   p = page - 3 + i
                }
                return (
                  <button key={p}
                    onClick={() => goPage(p)}
                    className={`w-8 h-8 rounded-lg text-sm font-medium transition-all
                      ${p === page
                        ? 'bg-primary text-white'
                        : 'text-default-500 hover:bg-content2'}`}>
                    {p}
                  </button>
                )
              })}
            </div>

            <Button size="sm" variant="flat" isDisabled={page >= pages}
              onPress={() => goPage(page + 1)}>
              <Icon d="M9 5l7 7-7 7" size={14} />
            </Button>
          </div>

          <span className="text-xs text-default-400">
            صفحة {page} من {pages.toLocaleString('ar-SA')} — إجمالي {total.toLocaleString('ar-SA')} جهة اتصال
          </span>
        </div>
      )}
    </div>
  )
}
