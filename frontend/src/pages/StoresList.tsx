import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button, Chip, Avatar, Tooltip, Spinner,
  Modal, ModalContent, ModalHeader, ModalBody, ModalFooter,
  Input, useDisclosure,
  Table, TableHeader, TableColumn, TableBody, TableRow, TableCell,
} from '@heroui/react'
import { api, StoreInfo, clearAuth } from '../api'
import { Field } from '../components/ui'

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

/* ── Stat card definitions ── */
const STATS = [
  {
    key: 'stores',
    label: 'المتاجر',
    glow: 'card-blue',
    gradient: 'from-blue-500/10 via-blue-500/5 to-transparent',
    border: 'border-blue-500/20 hover:border-blue-500/40',
    iconBg: 'bg-blue-500/15',
    iconColor: 'text-blue-400',
    numColor: 'text-blue-400',
    iconPaths: ['M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z', 'M9 22V12h6v10'],
    getValue: (s: StoreInfo[]) => s.length,
  },
  {
    key: 'products',
    label: 'إجمالي المنتجات',
    glow: 'card-green',
    gradient: 'from-emerald-500/10 via-emerald-500/5 to-transparent',
    border: 'border-emerald-500/20 hover:border-emerald-500/40',
    iconBg: 'bg-emerald-500/15',
    iconColor: 'text-emerald-400',
    numColor: 'text-emerald-400',
    iconPaths: ['M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4'],
    getValue: (s: StoreInfo[]) => s.reduce((a, x) => a + x.products_count, 0),
  },
  {
    key: 'ai',
    label: 'مع AI مُعدّ',
    glow: 'card-purple',
    gradient: 'from-violet-500/10 via-violet-500/5 to-transparent',
    border: 'border-violet-500/20 hover:border-violet-500/40',
    iconBg: 'bg-violet-500/15',
    iconColor: 'text-violet-400',
    numColor: 'text-violet-400',
    iconPaths: [
      'M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z',
    ],
    getValue: (s: StoreInfo[]) => s.filter(x => x.has_ai_config).length,
  },
  {
    key: 'sync',
    label: 'تمت المزامنة',
    glow: 'card-amber',
    gradient: 'from-amber-500/10 via-amber-500/5 to-transparent',
    border: 'border-amber-500/20 hover:border-amber-500/40',
    iconBg: 'bg-amber-500/15',
    iconColor: 'text-amber-400',
    numColor: 'text-amber-400',
    iconPaths: [
      'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15',
    ],
    getValue: (s: StoreInfo[]) => s.filter(x => x.last_sync !== 'never').length,
  },
]

export default function StoresList() {
  const navigate = useNavigate()
  const [stores, setStores] = useState<StoreInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [env, setEnv] = useState<Record<string, unknown>>({})
  const [msg, setMsg] = useState('')

  const { isOpen, onOpen, onClose } = useDisclosure()
  const [regStoreId, setRegStoreId]   = useState('')
  const [regToken, setRegToken]       = useState('')
  const [regRefresh, setRegRefresh]   = useState('')
  const [regName, setRegName]         = useState('')
  const [regLoading, setRegLoading]   = useState(false)
  const [regError, setRegError]       = useState('')

  useEffect(() => { loadData() }, [])

  const [dbTesting, setDbTesting] = useState(false)
  const [dbTestResult, setDbTestResult] = useState<string>('')

  async function loadData() {
    setLoading(true)
    try {
      const [storeRes, envRes] = await Promise.all([api.listStores(), api.envCheck()])
      setStores(storeRes.stores)
      setEnv(envRes)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  async function handleForceSync() {
    setSyncing(true); setMsg('')
    try { setMsg((await api.forceDbSync()).message) }
    catch (e: unknown) { setMsg(e instanceof Error ? e.message : 'خطأ') }
    finally { setSyncing(false) }
  }

  async function handleDbTest() {
    setDbTesting(true); setDbTestResult('')
    try {
      const r = await api.dbTest()
      if (r.ok) {
        let line = `✅ قاعدة البيانات تعمل — write/read/delete نجحوا. ` +
                   `محفوظ فعلياً: ${r.store_count} متجر | في الذاكرة: ${r.in_memory_stores}`
        // Hint when DB has more stores than memory — likely silent skip on load
        if (r.store_count > r.in_memory_stores) {
          line += `  ⚠️ ${r.store_count - r.in_memory_stores} متجر موجود في DB لكن مش محمّل! اضغط "إعادة تحميل من DB"`
        }
        setDbTestResult(line)
      } else {
        setDbTestResult(
          `❌ فشل التشخيص — connected:${r.connected} write:${r.write_ok} ` +
          `read:${r.read_ok} delete:${r.delete_ok}` +
          (r.error ? ` — ${r.error}` : '')
        )
      }
    } catch (e: unknown) {
      setDbTestResult(`❌ خطأ: ${e instanceof Error ? e.message : 'unknown'}`)
    } finally { setDbTesting(false) }
  }

  async function handleReloadFromDb() {
    setDbTesting(true); setDbTestResult('')
    try {
      const r = await api.reloadFromDb()
      setDbTestResult(
        `✅ ${r.message}` + (r.loaded > 0 ? ` — تم استرجاع ${r.loaded} متجر! 🎉` : '')
      )
      await loadData()
    } catch (e: unknown) {
      setDbTestResult(`❌ خطأ: ${e instanceof Error ? e.message : 'unknown'}`)
    } finally { setDbTesting(false) }
  }

  async function handleReset(storeId: string) {
    if (!confirm(`إعادة تعيين كلمة مرور متجر ${storeId}؟`)) return
    try {
      await api.resetPassword(storeId)
      setMsg(`تمت إعادة التعيين — كلمة المرور الجديدة: ${storeId}`)
    } catch (e: unknown) { setMsg(e instanceof Error ? e.message : 'خطأ') }
  }

  async function handleRegister() {
    if (!regStoreId || !regToken) { setRegError('معرف المتجر والـ Access Token مطلوبان'); return }
    setRegLoading(true); setRegError('')
    try {
      const res = await fetch('/admin/stores/register', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('admin_token')}`,
        },
        body: JSON.stringify({
          store_id: regStoreId, access_token: regToken,
          refresh_token: regRefresh, store_name: regName,
        }),
      })
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail) }
      onClose(); loadData()
    } catch (e: unknown) { setRegError(e instanceof Error ? e.message : 'خطأ') }
    finally { setRegLoading(false) }
  }

  function logout() { clearAuth(); navigate('/login', { replace: true }) }
  const dbConnected = Boolean(env['DB_CONNECTED'])

  return (
    <div className="min-h-screen bg-background p-6 space-y-6" dir="rtl">

      {/* ════════════════ HEADER ════════════════ */}
      <div className="flex items-center justify-between">
        {/* Brand */}
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-teal-500 to-cyan-600 flex items-center justify-center shadow-lg shadow-teal-500/30 flex-shrink-0">
            <Icon paths="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-xl font-black text-foreground leading-tight">لوحة التحكم</h1>
            <p className="text-xs text-slate-500 mt-0.5">إدارة جميع المتاجر</p>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          {/* DB badge */}
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold border ${
            dbConnected
              ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-400'
              : 'bg-red-500/10 border-red-500/25 text-red-400'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
              dbConnected ? 'bg-emerald-400 animate-pulse-dot' : 'bg-red-400'
            }`} />
            {dbConnected ? 'DB متصل' : 'DB غير متصل'}
          </div>

          <button
            onClick={() => navigate('/admin/platform-ops')}
            className="flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold border bg-sky-500/10 border-sky-500/25 text-sky-400 hover:bg-sky-500/15"
            title="لقطة تشغيلية للمنصة كاملة"
          >
            <Icon paths={['M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z']} size={13} />
            لوحة العمليات
          </button>

          <button
            onClick={onOpen}
            className="flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold border bg-content1 border-divider text-default-600 hover:text-foreground hover:border-slate-500 hover:bg-content2"
          >
            <Icon paths="M12 4v16m8-8H4" size={13} />
            تسجيل متجر
          </button>

          <button
            onClick={handleForceSync}
            disabled={syncing}
            className="flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold border bg-amber-500/10 border-amber-500/25 text-amber-400 hover:bg-amber-500/15 disabled:opacity-60"
          >
            {syncing
              ? <Spinner size="sm" color="warning" className="scale-75" />
              : <Icon paths="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" size={13} />
            }
            مزامنة DB
          </button>

          <button
            onClick={handleDbTest}
            disabled={dbTesting}
            className="flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold border bg-violet-500/10 border-violet-500/25 text-violet-400 hover:bg-violet-500/15 disabled:opacity-60"
            title="اختبار write/read/delete على قاعدة البيانات"
          >
            {dbTesting
              ? <Spinner size="sm" color="secondary" className="scale-75" />
              : <Icon paths={['M9 12l2 2 4-4', 'M21 12a9 9 0 11-18 0 9 9 0 0118 0z']} size={13} />
            }
            تشخيص DB
          </button>

          <button
            onClick={handleReloadFromDb}
            disabled={dbTesting}
            className="flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold border bg-cyan-500/10 border-cyan-500/25 text-cyan-400 hover:bg-cyan-500/15 disabled:opacity-60"
            title="إعادة تحميل المتاجر من قاعدة البيانات للذاكرة"
          >
            {dbTesting
              ? <Spinner size="sm" color="primary" className="scale-75" />
              : <Icon paths={['M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4', 'M7 10l5 5 5-5', 'M12 15V3']} size={13} />
            }
            تحميل من DB
          </button>

          <button
            onClick={logout}
            className="flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold border bg-red-500/10 border-red-500/25 text-red-400 hover:bg-red-500/15"
          >
            <Icon paths="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" size={13} />
            خروج
          </button>
        </div>
      </div>

      {/* ════════════════ CRITICAL: DB DISCONNECTED BANNER ════════════════ */}
      {!loading && !dbConnected && (
        <div className="rounded-2xl border border-red-500/40 bg-red-500/10 p-5 space-y-3">
          <div className="flex items-start gap-3">
            <div className="w-9 h-9 rounded-xl bg-red-500/20 flex items-center justify-center flex-shrink-0">
              <Icon paths="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" size={18} className="text-red-400" />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="font-bold text-red-300 text-sm mb-1">⚠️ قاعدة البيانات غير متصلة</h3>
              <p className="text-xs text-red-300/80 leading-relaxed">
                كل المتاجر اللي بتسجّلها هتختفي عند أول إعادة تشغيل أو deploy.
                {' '}افتح Railway → تأكد إن خدمة Postgres شغّالة وإن{' '}
                <code className="bg-red-500/15 px-1.5 py-0.5 rounded text-red-200">DATABASE_URL</code>
                {' '}موجود في environment variables بتاع الـ backend service.
              </p>
            </div>
            <button
              onClick={handleDbTest}
              disabled={dbTesting}
              className="flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-bold bg-red-500/15 border border-red-500/30 text-red-200 hover:bg-red-500/25 disabled:opacity-60 flex-shrink-0"
            >
              {dbTesting ? <Spinner size="sm" color="danger" className="scale-75" /> : '🔍'}
              تشخيص DB
            </button>
          </div>
          {dbTestResult && (
            <div className={`text-xs px-3 py-2 rounded-lg border font-mono ${
              dbTestResult.startsWith('✅')
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                : 'bg-red-500/15 border-red-500/30 text-red-200'
            }`}>
              {dbTestResult}
            </div>
          )}
        </div>
      )}

      {/* ════════════════ INFO BANNER (when DB connected but test result shown) ════════════════ */}
      {!loading && dbConnected && dbTestResult && (
        <div className={`rounded-xl border px-4 py-3 text-sm flex items-start gap-3 ${
          dbTestResult.startsWith('✅')
            ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-300'
            : 'bg-amber-500/10 border-amber-500/25 text-amber-300'
        }`}>
          <span className="font-mono text-xs flex-1">{dbTestResult}</span>
          <button onClick={() => setDbTestResult('')} className="opacity-60 hover:opacity-100">
            <Icon paths="M6 18L18 6M6 6l12 12" size={14} />
          </button>
        </div>
      )}

      {/* ════════════════ TOAST ════════════════ */}
      {msg && (
        <div className="flex items-center gap-3 bg-emerald-500/10 border border-emerald-500/25 rounded-xl px-4 py-3 text-sm text-emerald-400">
          <Icon paths="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" size={16} className="flex-shrink-0" />
          <span className="flex-1">{msg}</span>
          <button onClick={() => setMsg('')} className="text-emerald-600 hover:text-emerald-400">
            <Icon paths="M6 18L18 6M6 6l12 12" size={14} />
          </button>
        </div>
      )}

      {/* ════════════════ STATS ════════════════ */}
      <div className="grid grid-cols-4 gap-4">
        {STATS.map(s => (
          <div
            key={s.key}
            className={`relative overflow-hidden rounded-2xl bg-content1 border ${s.border} p-5 ${s.glow} transition-all duration-300`}
          >
            <div className={`absolute inset-0 bg-gradient-to-br ${s.gradient} pointer-events-none`} />
            <div className="relative flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs text-slate-500 font-medium mb-3 truncate">{s.label}</p>
                <p className={`text-4xl font-black tracking-tight leading-none ${s.numColor}`}>
                  {s.getValue(stores)}
                </p>
              </div>
              <div className={`w-10 h-10 ${s.iconBg} rounded-xl flex items-center justify-center flex-shrink-0 ${s.iconColor}`}>
                <Icon paths={s.iconPaths} size={18} />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* ════════════════ TABLE ════════════════ */}
      <div className="rounded-2xl bg-content1 border border-divider overflow-hidden">

        {/* Table header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-divider">
          <h2 className="font-bold text-foreground text-sm flex items-center gap-2.5">
            <span className="w-1 h-5 bg-gradient-to-b from-blue-400 to-indigo-500 rounded-full" />
            المتاجر المسجلة
          </h2>
          <span className="text-xs text-slate-500 bg-content2 px-2.5 py-1 rounded-lg border border-divider">
            {stores.length} متجر
          </span>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-24">
            <Spinner size="lg" color="primary" />
          </div>
        ) : (
          <Table
            aria-label="stores-table"
            classNames={{
              wrapper: 'bg-transparent shadow-none p-0 rounded-none',
              th: 'bg-content2 text-slate-500 text-xs font-semibold uppercase tracking-wide border-0 first:rounded-none last:rounded-none',
              td: 'py-3.5 border-b border-divider/60 last-of-type:border-0',
              tr: 'hover:bg-content2 transition-colors',
            }}
          >
            <TableHeader>
              <TableColumn>المتجر</TableColumn>
              <TableColumn>النطاق</TableColumn>
              <TableColumn>المنتجات</TableColumn>
              <TableColumn>AI</TableColumn>
              <TableColumn>آخر مزامنة</TableColumn>
              <TableColumn>الإجراءات</TableColumn>
            </TableHeader>
            <TableBody emptyContent={
              <div className="py-20 text-center">
                <div className="w-16 h-16 bg-content2 rounded-2xl flex items-center justify-center mx-auto mb-4">
                  <Icon paths={['M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z', 'M9 22V12h6v10']} size={26} className="text-slate-600" />
                </div>
                <p className="text-slate-400 text-sm font-semibold">لا يوجد متاجر مسجلة</p>
                <p className="text-slate-600 text-xs mt-1">أضف متجراً جديداً للبدء</p>
              </div>
            }>
              {stores.map(s => (
                <TableRow key={s.store_id}>
                  <TableCell>
                    <div className="flex items-center gap-3 text-right">
                      <Avatar
                        src={s.store_avatar || undefined}
                        name={s.store_name[0]}
                        size="sm"
                        className="bg-blue-500/20 text-blue-400 font-bold flex-shrink-0"
                      />
                      <div className="min-w-0">
                        <p className="font-semibold text-sm text-foreground truncate">
                          {s.store_name}
                        </p>
                        <p className="text-xs text-slate-600 font-mono truncate">{s.store_id}</p>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <span className="text-sm text-slate-400">{s.store_domain || '—'}</span>
                  </TableCell>
                  <TableCell>
                    <span className="inline-flex items-center text-sm font-bold text-blue-400 bg-blue-500/10 border border-blue-500/20 px-2.5 py-0.5 rounded-lg">
                      {s.products_count}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="sm"
                      color={s.has_ai_config ? 'success' : 'default'}
                      variant="flat"
                      classNames={{ content: 'font-semibold text-xs' }}
                    >
                      {s.has_ai_config ? '✓ مُعدّ' : 'env'}
                    </Chip>
                  </TableCell>
                  <TableCell>
                    <span className="text-xs text-slate-500">
                      {s.last_sync === 'never'
                        ? 'لم تتم بعد'
                        : new Date(s.last_sync).toLocaleString('ar-SA')}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1.5">
                      <Tooltip content="إعادة تعيين كلمة المرور">
                        <button
                          onClick={() => handleReset(s.store_id)}
                          className="w-8 h-8 flex items-center justify-center rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 hover:bg-amber-500/20 transition-colors"
                        >
                          <Icon paths={['M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z', 'M12 7V7a4 4 0 018 0v4H4V7a4 4 0 018 0z']} size={13} />
                        </button>
                      </Tooltip>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {/* ════════════════ REGISTER MODAL ════════════════ */}
      <Modal isOpen={isOpen} onClose={onClose} placement="center">
        <ModalContent className="bg-content1 border border-divider">
          <ModalHeader className="text-foreground font-bold border-b border-divider pb-4">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 bg-blue-500/15 rounded-xl flex items-center justify-center text-blue-400">
                <Icon paths="M12 4v16m8-8H4" size={15} />
              </div>
              تسجيل متجر جديد
            </div>
          </ModalHeader>
          <ModalBody className="gap-3 pt-4">
            <Field label="معرف المتجر *">
              <Input
                placeholder="store-123"
                value={regStoreId}
                onValueChange={setRegStoreId}
                variant="bordered"
                classNames={{ inputWrapper: 'border-default-200 hover:border-default-300 bg-default-50 h-12 rounded-xl' }}
              />
            </Field>
            <Field label="Access Token *">
              <Input
                placeholder="ey..."
                type="password"
                value={regToken}
                onValueChange={setRegToken}
                variant="bordered"
                classNames={{ inputWrapper: 'border-default-200 hover:border-default-300 bg-default-50 h-12 rounded-xl' }}
              />
            </Field>
            <Field label="Refresh Token">
              <Input
                placeholder="اختياري"
                value={regRefresh}
                onValueChange={setRegRefresh}
                variant="bordered"
                classNames={{ inputWrapper: 'border-default-200 hover:border-default-300 bg-default-50 h-12 rounded-xl' }}
              />
            </Field>
            <Field label="اسم المتجر">
              <Input
                placeholder="متجري"
                value={regName}
                onValueChange={setRegName}
                variant="bordered"
                classNames={{ inputWrapper: 'border-default-200 hover:border-default-300 bg-default-50 h-12 rounded-xl' }}
              />
            </Field>
            {regError && (
              <div className="flex items-center gap-2 bg-red-500/10 border border-red-500/20 rounded-xl px-3 py-2.5 text-red-400 text-sm">
                <Icon paths="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" size={15} className="flex-shrink-0" />
                {regError}
              </div>
            )}
          </ModalBody>
          <ModalFooter className="border-t border-divider pt-4">
            <Button variant="flat" onPress={onClose} className="text-slate-400 bg-content2">
              إلغاء
            </Button>
            <Button color="primary" isLoading={regLoading} onPress={handleRegister} className="font-bold">
              تسجيل المتجر
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </div>
  )
}
