import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button, Card, CardBody, CardHeader, Chip, Divider, Input,
  Select, SelectItem, Spinner, Table, TableBody, TableCell,
  TableColumn, TableHeader, TableRow,
} from '@heroui/react'
import { api, ApiError, AuditRow, getIsSuper } from '../api'

/* ─────────────────────────── Helpers ────────────────────────────────── */

const ACTION_LABEL: Record<string, { label: string; color: 'success' | 'warning' | 'danger' | 'primary' | 'default' }> = {
  set_llm_budget:            { label: 'تعديل حد الميزانية',    color: 'warning' },
  update_ai_settings:        { label: 'تحديث إعدادات الذكاء',  color: 'warning' },
  change_store_password:     { label: 'تغيير كلمة المرور',     color: 'danger'  },
  employee_created:          { label: 'إضافة موظف',            color: 'primary' },
  employee_updated:          { label: 'تعديل موظف',            color: 'default' },
  employee_deleted:          { label: 'حذف موظف',              color: 'danger'  },
  super_viewed_conversation: { label: 'فتح محادثة عميل (مدير)', color: 'warning' },
  super_opened_stream:       { label: 'فتح تدفق مباشر (مدير)',  color: 'warning' },
}

function fmtTs(iso: string): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleString('ar-EG', {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return iso }
}

// Compact, human-readable summary of the details JSON. We avoid dumping
// raw JSON because the audit log is read by humans during incident
// response — they don't need to parse strings.
function summariseDetails(action: string, details: Record<string, unknown>): string {
  switch (action) {
    case 'set_llm_budget': {
      const applied = details.applied as number | null
      return applied === null
        ? 'إعادة للحد الافتراضي'
        : applied === 0
          ? 'إلغاء الحد (للمدير العام فقط)'
          : `الحد الجديد: ${applied?.toLocaleString('ar-EG')} توكن`
    }
    case 'update_ai_settings': {
      const changed = (details.secret_fields_changed as string[]) || []
      const other   = details.other_changes as Record<string, unknown> | undefined
      const parts: string[] = []
      if (changed.length) parts.push(`مفاتيح مغيّرة: ${changed.join('، ')}`)
      if (other && Object.keys(other).length) parts.push(`إعدادات: ${Object.keys(other).join('، ')}`)
      return parts.join(' · ') || '—'
    }
    case 'employee_created':
      return `${details.email || ''} (${details.role || 'agent'})`
    case 'employee_updated': {
      const changes = (details.changes as Record<string, unknown>) || {}
      return Object.keys(changes).join('، ') || '—'
    }
    case 'employee_deleted':
      return String(details.email || details.employee_id || '—')
    case 'change_store_password':
      return 'تم تغيير كلمة مرور المتجر'
    case 'super_viewed_conversation': {
      const reason = String(details.reason || '').slice(0, 80)
      const sid    = String(details.session_id || '').slice(0, 8)
      return reason ? `${reason} · session: ${sid}…` : `session: ${sid}…`
    }
    case 'super_opened_stream':
      return String(details.reason || '—').slice(0, 100)
    default:
      // Fallback: short JSON for unknown actions so a new action type
      // still renders sensibly without a code change.
      try { return JSON.stringify(details).slice(0, 120) } catch { return '—' }
  }
}

/* ─────────────────────────── Page ───────────────────────────────────── */

export default function AuditLog() {
  const navigate = useNavigate()
  const [rows, setRows]       = useState<AuditRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string>('')
  const [actionFilter, setActionFilter] = useState<string>('')
  const [storeFilter, setStoreFilter]   = useState<string>('')

  async function load() {
    setLoading(true)
    setError('')
    try {
      const res = await api.auditLogGlobal({
        action:   actionFilter || undefined,
        store_id: storeFilter  || undefined,
        limit:    300,
      })
      setRows(res.rows)
    } catch (e) {
      const msg = e instanceof ApiError ? e.detail : (e instanceof Error ? e.message : '—')
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!getIsSuper()) { navigate('/login', { replace: true }); return }
    load()
  }, [actionFilter, storeFilter])

  return (
    <div className="min-h-screen bg-content2 p-4 md:p-6" dir="rtl">
      <div className="max-w-7xl mx-auto space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl md:text-3xl font-extrabold text-foreground">سجل الإجراءات الحساسة</h1>
            <p className="text-sm text-default-500 mt-1">
              كل تغيير في الميزانية، المفاتيح، كلمات المرور، أو الموظفين — مع المنفّذ ووقت الإجراء.
              لا يحتوي السجل على القيم الحساسة نفسها (لا مفاتيح، لا كلمات مرور).
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="flat" onPress={() => navigate('/admin/platform-ops')}>
              لوحة العمليات
            </Button>
            <Button color="primary" onPress={load} isLoading={loading}>تحديث</Button>
          </div>
        </div>

        {/* Filters */}
        <Card>
          <CardBody className="flex flex-wrap gap-3 items-end">
            <Select
              size="sm"
              label="نوع الإجراء"
              selectedKeys={actionFilter ? [actionFilter] : []}
              onSelectionChange={(keys) => setActionFilter(Array.from(keys)[0] as string || '')}
              className="max-w-xs"
            >
              <SelectItem key="">الكل</SelectItem>
              <>{Object.entries(ACTION_LABEL).map(([k, v]) => (
                <SelectItem key={k}>{v.label}</SelectItem>
              ))}</>
            </Select>
            <Input
              size="sm"
              label="معرّف المتجر"
              placeholder="اختياري — فلترة على متجر واحد"
              value={storeFilter}
              onValueChange={setStoreFilter}
              className="max-w-xs"
            />
            {(actionFilter || storeFilter) && (
              <Button size="sm" variant="light" onPress={() => { setActionFilter(''); setStoreFilter('') }}>
                مسح الفلترة
              </Button>
            )}
          </CardBody>
        </Card>

        {/* Table */}
        <Card>
          <CardHeader>
            <h3 className="font-bold">آخر {rows.length} حدث</h3>
          </CardHeader>
          <Divider />
          <CardBody className="overflow-x-auto">
            {error && (
              <div className="bg-rose-50 border border-rose-200 text-rose-700 rounded-lg p-3 text-sm mb-3">
                {error}
              </div>
            )}
            {loading && rows.length === 0 ? (
              <div className="flex justify-center py-10">
                <Spinner size="lg" color="primary" label="جاري التحميل..." />
              </div>
            ) : rows.length === 0 ? (
              <p className="text-center text-default-400 py-10">لا توجد إجراءات مسجّلة بعد ✅</p>
            ) : (
              <Table aria-label="سجل المراجعة" removeWrapper>
                <TableHeader>
                  <TableColumn>الوقت</TableColumn>
                  <TableColumn>الإجراء</TableColumn>
                  <TableColumn>المنفّذ</TableColumn>
                  <TableColumn>المتجر</TableColumn>
                  <TableColumn>التفاصيل</TableColumn>
                  <TableColumn>IP</TableColumn>
                </TableHeader>
                <TableBody>
                  {rows.map((r) => {
                    const ac = ACTION_LABEL[r.action] || { label: r.action, color: 'default' as const }
                    return (
                      <TableRow key={r.id}>
                        <TableCell className="text-xs whitespace-nowrap">{fmtTs(r.created_at)}</TableCell>
                        <TableCell>
                          <Chip size="sm" color={ac.color} variant="flat">{ac.label}</Chip>
                        </TableCell>
                        <TableCell className="font-mono text-xs">{r.actor}</TableCell>
                        <TableCell>
                          {r.target_store ? (
                            <button
                              onClick={() => navigate(`/store/${r.target_store}`)}
                              className="text-sky-600 hover:underline text-sm"
                            >
                              {r.target_store}
                            </button>
                          ) : <span className="text-default-400">—</span>}
                        </TableCell>
                        <TableCell className="text-sm text-default-700 max-w-xs truncate" title={summariseDetails(r.action, r.details)}>
                          {summariseDetails(r.action, r.details)}
                        </TableCell>
                        <TableCell className="font-mono text-[11px] text-default-400">{r.ip || '—'}</TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  )
}
