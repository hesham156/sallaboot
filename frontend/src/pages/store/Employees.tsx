import { useEffect, useState } from 'react'
import {
  Button, Input, Modal, ModalBody, ModalContent, ModalFooter, ModalHeader,
  Select, SelectItem, Spinner, Switch, useDisclosure,
} from '@heroui/react'
import {
  api, Employee, EmployeeCreateInput, EmployeeRatingStats,
  UnattributedRatings, getEmployee,
} from '../../api'
import { PageHeader } from '../../components/ui'

interface Props { storeId: string }

function Icon({ paths, size = 16, className = '' }: {
  paths: string | string[]; size?: number; className?: string
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

function relTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60)     return 'الآن'
  if (diff < 3600)   return `منذ ${Math.floor(diff / 60)} د`
  if (diff < 86400)  return `منذ ${Math.floor(diff / 3600)} س`
  if (diff < 604800) return `منذ ${Math.floor(diff / 86400)} يوم`
  return d.toLocaleDateString('ar-SA', { day: 'numeric', month: 'short', year: 'numeric' })
}

const ROLE_OPTIONS = [
  { key: 'agent',   label: 'موظف خدمة عملاء' },
  { key: 'manager', label: 'مدير' },
]

function formatRatedAt(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('ar-SA', {
    day: 'numeric', month: 'short',
    hour: '2-digit', minute: '2-digit',
  })
}

function ratingColor(avg: number): string {
  if (avg >= 4.5) return 'text-emerald-500'
  if (avg >= 3.5) return 'text-teal-500'
  if (avg >= 2.5) return 'text-amber-500'
  if (avg > 0)    return 'text-red-500'
  return 'text-default-400'
}

export default function Employees({ storeId }: Props) {
  const [items, setItems]     = useState<Employee[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr]         = useState('')
  const [editing, setEditing] = useState<Employee | null>(null)
  const [ratings, setRatings] = useState<Record<number, EmployeeRatingStats>>({})
  const [unattributed, setUnattributed] = useState<UnattributedRatings | null>(null)
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})

  // Form state shared by create + edit
  const [form, setForm] = useState<EmployeeCreateInput>({
    name: '', email: '', password: '', role: 'agent', active: true,
  })
  const [saving, setSaving] = useState(false)
  const [formErr, setFormErr] = useState('')

  const { isOpen, onOpen, onClose, onOpenChange } = useDisclosure()
  const sessionEmp = getEmployee()
  const isOwner = !sessionEmp  // employees can't manage other employees

  useEffect(() => { load() }, [storeId])

  async function load() {
    setLoading(true); setErr('')
    try {
      const [empRes, rateRes] = await Promise.all([
        api.listEmployees(storeId),
        api.employeesRatings(storeId).catch(() => null),
      ])
      setItems(empRes.employees)
      if (rateRes) {
        const map: Record<number, EmployeeRatingStats> = {}
        rateRes.employees.forEach(r => { map[r.employee_id] = r })
        setRatings(map)
        setUnattributed(rateRes.unattributed)
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'تعذر تحميل قائمة الموظفين')
    } finally { setLoading(false) }
  }

  function openCreate() {
    setEditing(null)
    setForm({ name: '', email: '', password: '', role: 'agent', active: true })
    setFormErr('')
    onOpen()
  }

  function openEdit(emp: Employee) {
    setEditing(emp)
    setForm({
      name: emp.name, email: emp.email, password: '',
      role: emp.role, active: emp.active,
    })
    setFormErr('')
    onOpen()
  }

  async function save() {
    setFormErr('')
    if (!form.name.trim() || !form.email.trim()) {
      setFormErr('الاسم والبريد مطلوبان'); return
    }
    if (!editing && (!form.password || form.password.length < 6)) {
      setFormErr('كلمة المرور مطلوبة (6 أحرف على الأقل)'); return
    }
    if (form.password && form.password.length < 6) {
      setFormErr('كلمة المرور قصيرة جداً (6 أحرف على الأقل)'); return
    }
    setSaving(true)
    try {
      if (editing) {
        await api.updateEmployee(storeId, editing.id, {
          name:   form.name.trim(),
          email:  form.email.trim(),
          role:   form.role,
          active: form.active,
          ...(form.password ? { password: form.password } : {}),
        })
      } else {
        await api.createEmployee(storeId, {
          name:     form.name.trim(),
          email:    form.email.trim(),
          password: form.password,
          role:     form.role,
          active:   form.active,
        })
      }
      onClose()
      await load()
    } catch (e) {
      setFormErr(e instanceof Error ? e.message : 'تعذر الحفظ')
    } finally { setSaving(false) }
  }

  async function remove(emp: Employee) {
    if (!confirm(`حذف الموظف "${emp.name}"؟ لن يستطيع تسجيل الدخول بعد ذلك.`)) return
    try {
      await api.deleteEmployee(storeId, emp.id)
      await load()
    } catch (e) {
      alert(e instanceof Error ? e.message : 'تعذر الحذف')
    }
  }

  async function toggleActive(emp: Employee) {
    try {
      await api.updateEmployee(storeId, emp.id, { active: !emp.active })
      await load()
    } catch (e) {
      alert(e instanceof Error ? e.message : 'تعذر تحديث الحالة')
    }
  }

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto" dir="rtl">

      {/* Header */}
      <div className="mb-6">
        <PageHeader
          title="الموظفون"
          subtitle="أضف موظفين برّد على المحادثات باسمهم، وسيظهر اسمهم في صندوق الدردشة وفي تقييم العميل."
          icon={['M16 7a4 4 0 11-8 0 4 4 0 018 0z', 'M12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z']}
          iconTone="warning"
          actions={isOwner && (
            <Button
              color="warning"
              variant="solid"
              onPress={openCreate}
              startContent={<Icon paths="M12 4v16m8-8H4" size={14} />}
              className="text-white font-bold"
            >
              موظف جديد
            </Button>
          )}
        />
      </div>

      {!isOwner && (
        <div className="mb-4 px-4 py-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-700 text-xs">
          إدارة الموظفين متاحة فقط لمالك المتجر. أنت مسجّل دخول كموظف.
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Spinner size="lg" color="warning" label="جاري التحميل..." />
        </div>
      ) : err ? (
        <div className="px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-600 text-sm">
          {err}
        </div>
      ) : items.length === 0 ? (
        <div className="border border-dashed border-divider rounded-3xl p-12 text-center bg-content2/40">
          <div className="w-16 h-16 mx-auto rounded-3xl bg-content1 border border-divider flex items-center justify-center mb-4">
            <Icon paths={['M16 7a4 4 0 11-8 0 4 4 0 018 0z', 'M12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z']} size={28} className="text-default-500" />
          </div>
          <p className="text-base font-semibold text-foreground">لا يوجد موظفون بعد</p>
          <p className="text-xs text-default-500 mt-1 mb-4">
            أضف أول موظف ليتمكّن من الرد على المحادثات باسمه.
          </p>
          {isOwner && (
            <Button color="warning" variant="flat" onPress={openCreate}>
              إضافة موظف
            </Button>
          )}
        </div>
      ) : (
        <>
        <div className="grid gap-3 md:grid-cols-2">
          {items.map(emp => {
            const stats = ratings[emp.id]
            const isExpanded = !!expanded[emp.id]
            return (
              <div
                key={emp.id}
                className={`bg-content1 border rounded-2xl p-4 transition-all ${
                  emp.active ? 'border-divider hover:border-amber-500/40'
                             : 'border-divider opacity-60'
                }`}
              >
                {/* Top row: avatar + identity + actions */}
                <div className="flex items-start gap-3">
                  <div className="w-11 h-11 rounded-full bg-gradient-to-br from-amber-500 to-orange-600 text-white font-bold flex items-center justify-center flex-shrink-0">
                    {emp.name.trim().charAt(0) || '?'}
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                      <p className="text-sm font-bold text-foreground truncate">{emp.name}</p>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${
                        emp.role === 'manager'
                          ? 'bg-violet-500/15 text-violet-500'
                          : 'bg-blue-500/15 text-blue-500'
                      }`}>
                        {emp.role === 'manager' ? 'مدير' : 'موظف'}
                      </span>
                      {!emp.active && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded font-semibold bg-default-500/15 text-default-500">
                          موقوف
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-default-500 truncate" dir="ltr">{emp.email}</p>
                    <p className="text-[10px] text-default-600 mt-1">أُضيف {relTime(emp.created_at)}</p>
                  </div>
                </div>

                {/* Ratings strip */}
                <div className="mt-3 border-t border-divider pt-3">
                  {stats && stats.count > 0 ? (
                    <>
                      <div className="flex items-center justify-between gap-2 mb-2">
                        <div className="flex items-baseline gap-1.5">
                          <span className={`text-2xl font-black ${ratingColor(stats.avg)}`}>
                            {stats.avg.toFixed(1)}
                          </span>
                          <span className="text-xs text-default-500">/ 5</span>
                          <span className="text-[11px] text-default-500 mr-2">
                            ({stats.count} تقييم)
                          </span>
                        </div>
                        <button
                          onClick={() => setExpanded({ ...expanded, [emp.id]: !isExpanded })}
                          className="text-[11px] font-bold text-amber-600 hover:text-amber-500"
                        >
                          {isExpanded ? 'إخفاء' : 'التفاصيل'}
                        </button>
                      </div>

                      {/* Tiny histogram bar — 5 stars left → 1 right */}
                      <div className="flex items-center gap-1 h-6">
                        {[5, 4, 3, 2, 1].map(star => {
                          const n = stats.distribution[star - 1] || 0
                          const pct = stats.count ? (n / stats.count) * 100 : 0
                          const barClass =
                            star >= 4 ? 'bg-emerald-500' :
                            star === 3 ? 'bg-amber-500' :
                                          'bg-red-500'
                          return (
                            <div
                              key={star}
                              className="flex-1 flex flex-col items-center gap-0.5"
                              title={`${star} نجوم — ${n} تقييم`}
                            >
                              <div className="w-full h-3 rounded-sm bg-content2 overflow-hidden relative">
                                <div
                                  className={`absolute inset-y-0 right-0 ${barClass}`}
                                  style={{ width: `${pct}%` }}
                                />
                              </div>
                              <span className="text-[9px] text-default-500">{star}★</span>
                            </div>
                          )
                        })}
                      </div>

                      {/* Recent ratings details */}
                      {isExpanded && stats.recent.length > 0 && (
                        <div className="mt-3 space-y-2 max-h-56 overflow-y-auto">
                          {stats.recent.map(r => (
                            <div
                              key={r.session_id + r.rated_at}
                              className="bg-content2/60 rounded-xl px-3 py-2 text-xs"
                            >
                              <div className="flex items-center justify-between gap-2 mb-0.5">
                                <span className="font-bold text-amber-500">
                                  {'★'.repeat(r.rating)}{'☆'.repeat(5 - r.rating)}
                                </span>
                                <span className="text-[10px] text-default-500">{formatRatedAt(r.rated_at)}</span>
                              </div>
                              {r.customer_name && (
                                <p className="text-[11px] text-default-500">من: {r.customer_name}</p>
                              )}
                              {r.comment && r.comment !== `CSAT: ${stats.name}` && r.comment !== 'CSAT' && (
                                <p className="text-[11px] text-foreground mt-1">{r.comment}</p>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  ) : (
                    <p className="text-[11px] text-default-500">لا توجد تقييمات لهذا الموظف بعد.</p>
                  )}
                </div>

                {isOwner && (
                  <div className="flex items-center gap-1.5 mt-3 pt-3 border-t border-divider">
                    <Button
                      size="sm" variant="flat"
                      onPress={() => openEdit(emp)}
                      className="text-xs"
                      startContent={<Icon paths="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" size={12} />}
                    >
                      تعديل
                    </Button>
                    <Button
                      size="sm" variant="flat" color={emp.active ? 'default' : 'success'}
                      onPress={() => toggleActive(emp)}
                      className="text-xs"
                    >
                      {emp.active ? 'إيقاف' : 'تفعيل'}
                    </Button>
                    <Button
                      size="sm" variant="flat" color="danger"
                      onPress={() => remove(emp)}
                      className="text-xs"
                      startContent={<Icon paths={['M3 6h18', 'M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6', 'M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2']} size={12} />}
                    >
                      حذف
                    </Button>
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* Unattributed ratings summary (legacy rating-bar or pre-flow ratings) */}
        {unattributed && unattributed.count > 0 && (
          <div className="mt-6 bg-content2/40 border border-divider rounded-2xl p-4">
            <div className="flex items-center justify-between gap-2 mb-2">
              <p className="text-sm font-bold text-foreground">
                تقييمات غير منسوبة لموظف
              </p>
              <span className="text-xs text-default-500">
                {unattributed.count} تقييم · متوسط {unattributed.avg.toFixed(1)}
              </span>
            </div>
            <p className="text-[11px] text-default-500">
              هذه تقييمات وصلت قبل إضافة نظام الموظفين أو من شريط التقييم العام في الويدجت.
            </p>
          </div>
        )}
        </>
      )}

      {/* Create/edit modal */}
      <Modal isOpen={isOpen} onOpenChange={onOpenChange} placement="center" backdrop="blur" size="md">
        <ModalContent>
          {() => (
            <>
              <ModalHeader className="flex flex-col gap-1">
                <span className="text-base font-bold">
                  {editing ? `تعديل: ${editing.name}` : 'موظف جديد'}
                </span>
                <span className="text-xs text-default-500 font-normal">
                  {editing ? 'اترك كلمة المرور فارغة إذا لم ترد تغييرها' : 'سيستخدم البريد وكلمة المرور لتسجيل الدخول'}
                </span>
              </ModalHeader>
              <ModalBody className="space-y-4 pt-2" dir="rtl">
                <Input
                  label="الاسم"
                  labelPlacement="outside"
                  placeholder="مثلاً: شروق"
                  value={form.name}
                  onValueChange={v => setForm({ ...form, name: v })}
                  variant="bordered"
                  classNames={{ label: 'text-xs font-semibold text-default-600' }}
                />
                <Input
                  label="البريد الإلكتروني"
                  labelPlacement="outside"
                  type="email"
                  placeholder="agent@store.com"
                  value={form.email}
                  onValueChange={v => setForm({ ...form, email: v })}
                  variant="bordered"
                  classNames={{ label: 'text-xs font-semibold text-default-600', input: 'text-left', inputWrapper: 'text-left' }}
                />
                <Input
                  label={editing ? 'كلمة مرور جديدة (اختياري)' : 'كلمة المرور'}
                  labelPlacement="outside"
                  type="password"
                  placeholder="6 أحرف فأكثر"
                  value={form.password}
                  onValueChange={v => setForm({ ...form, password: v })}
                  variant="bordered"
                  classNames={{ label: 'text-xs font-semibold text-default-600' }}
                />
                <Select
                  label="الدور"
                  labelPlacement="outside"
                  placeholder="اختر الدور"
                  selectedKeys={[form.role || 'agent']}
                  onSelectionChange={keys => {
                    const v = Array.from(keys)[0] as string
                    setForm({ ...form, role: v })
                  }}
                  variant="bordered"
                  classNames={{ label: 'text-xs font-semibold text-default-600' }}
                >
                  {ROLE_OPTIONS.map(opt => (
                    <SelectItem key={opt.key}>{opt.label}</SelectItem>
                  ))}
                </Select>
                <div className="flex items-center justify-between px-1 pt-1">
                  <span className="text-sm font-semibold text-default-700">حساب مفعّل</span>
                  <Switch
                    isSelected={form.active !== false}
                    onValueChange={v => setForm({ ...form, active: v })}
                    color="warning"
                  />
                </div>
                {formErr && (
                  <div className="text-xs font-semibold text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                    {formErr}
                  </div>
                )}
              </ModalBody>
              <ModalFooter>
                <Button variant="light" onPress={onClose}>إلغاء</Button>
                <Button
                  color="warning"
                  isLoading={saving}
                  onPress={save}
                  className="bg-gradient-to-br from-amber-500 to-orange-600 text-white font-bold"
                >
                  {editing ? 'حفظ التغييرات' : 'إضافة'}
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>
    </div>
  )
}
