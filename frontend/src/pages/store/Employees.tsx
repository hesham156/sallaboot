import { useEffect, useState } from 'react'
import {
  Button, Input, Modal, ModalBody, ModalContent, ModalFooter, ModalHeader,
  Select, SelectItem, Spinner, Switch, useDisclosure,
} from '@heroui/react'
import { api, Employee, EmployeeCreateInput, getEmployee } from '../../api'

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

export default function Employees({ storeId }: Props) {
  const [items, setItems]     = useState<Employee[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr]         = useState('')
  const [editing, setEditing] = useState<Employee | null>(null)

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
      const res = await api.listEmployees(storeId)
      setItems(res.employees)
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
      <div className="flex items-start justify-between gap-3 mb-6 flex-wrap">
        <div>
          <h1 className="text-xl md:text-2xl font-black text-foreground flex items-center gap-2">
            <span className="w-9 h-9 rounded-2xl bg-amber-500/15 text-amber-500 flex items-center justify-center">
              <Icon paths={['M16 7a4 4 0 11-8 0 4 4 0 018 0z', 'M12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z']} size={18} />
            </span>
            الموظفون
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            أضف موظفين برّد على المحادثات باسمهم، وسيظهر اسمهم في صندوق الدردشة وفي تقييم العميل.
          </p>
        </div>

        {isOwner && (
          <Button
            color="warning"
            variant="solid"
            onPress={openCreate}
            startContent={<Icon paths="M12 4v16m8-8H4" size={14} />}
            className="bg-gradient-to-br from-amber-500 to-orange-600 text-white font-bold"
          >
            موظف جديد
          </Button>
        )}
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
            <Icon paths={['M16 7a4 4 0 11-8 0 4 4 0 018 0z', 'M12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z']} size={28} className="text-slate-500" />
          </div>
          <p className="text-base font-semibold text-foreground">لا يوجد موظفون بعد</p>
          <p className="text-xs text-slate-500 mt-1 mb-4">
            أضف أول موظف ليتمكّن من الرد على المحادثات باسمه.
          </p>
          {isOwner && (
            <Button color="warning" variant="flat" onPress={openCreate}>
              إضافة موظف
            </Button>
          )}
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {items.map(emp => (
            <div
              key={emp.id}
              className={`bg-content1 border rounded-2xl p-4 flex items-start gap-3 transition-all ${
                emp.active ? 'border-divider hover:border-amber-500/40'
                           : 'border-divider opacity-60'
              }`}
            >
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
                    <span className="text-[10px] px-1.5 py-0.5 rounded font-semibold bg-slate-500/15 text-slate-500">
                      موقوف
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-500 truncate" dir="ltr">{emp.email}</p>
                <p className="text-[10px] text-slate-600 mt-1">أُضيف {relTime(emp.created_at)}</p>

                {isOwner && (
                  <div className="flex items-center gap-1.5 mt-3">
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
            </div>
          ))}
        </div>
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
                <span className="text-xs text-slate-500 font-normal">
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
                  classNames={{ label: 'text-xs font-semibold text-slate-600' }}
                />
                <Input
                  label="البريد الإلكتروني"
                  labelPlacement="outside"
                  type="email"
                  placeholder="agent@store.com"
                  value={form.email}
                  onValueChange={v => setForm({ ...form, email: v })}
                  variant="bordered"
                  classNames={{ label: 'text-xs font-semibold text-slate-600', input: 'text-left', inputWrapper: 'text-left' }}
                />
                <Input
                  label={editing ? 'كلمة مرور جديدة (اختياري)' : 'كلمة المرور'}
                  labelPlacement="outside"
                  type="password"
                  placeholder="6 أحرف فأكثر"
                  value={form.password}
                  onValueChange={v => setForm({ ...form, password: v })}
                  variant="bordered"
                  classNames={{ label: 'text-xs font-semibold text-slate-600' }}
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
                  classNames={{ label: 'text-xs font-semibold text-slate-600' }}
                >
                  {ROLE_OPTIONS.map(opt => (
                    <SelectItem key={opt.key}>{opt.label}</SelectItem>
                  ))}
                </Select>
                <div className="flex items-center justify-between px-1 pt-1">
                  <span className="text-sm font-semibold text-slate-700">حساب مفعّل</span>
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
