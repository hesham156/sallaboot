import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, CardBody, CardHeader,
  Table, TableHeader, TableColumn, TableBody, TableRow, TableCell,
  Button, Chip, Avatar, Tooltip, Spinner,
  Modal, ModalContent, ModalHeader, ModalBody, ModalFooter,
  Input, useDisclosure, Divider,
} from '@heroui/react'
import { api, StoreInfo, clearAuth } from '../api'

export default function StoresList() {
  const navigate = useNavigate()
  const [stores, setStores] = useState<StoreInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [env, setEnv] = useState<Record<string, unknown>>({})
  const [msg, setMsg] = useState('')

  // Register store modal
  const { isOpen, onOpen, onClose } = useDisclosure()
  const [regStoreId, setRegStoreId] = useState('')
  const [regToken, setRegToken] = useState('')
  const [regRefresh, setRegRefresh] = useState('')
  const [regName, setRegName] = useState('')
  const [regLoading, setRegLoading] = useState(false)
  const [regError, setRegError] = useState('')

  useEffect(() => { loadData() }, [])

  async function loadData() {
    setLoading(true)
    try {
      const [storeRes, envRes] = await Promise.all([
        api.listStores(),
        api.envCheck(),
      ])
      setStores(storeRes.stores)
      setEnv(envRes)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  async function handleForceSync() {
    setSyncing(true)
    setMsg('')
    try {
      const res = await api.forceDbSync()
      setMsg(res.message)
    } catch (e: unknown) {
      setMsg(e instanceof Error ? e.message : 'خطأ')
    } finally {
      setSyncing(false)
    }
  }

  async function handleReset(storeId: string) {
    if (!confirm(`إعادة تعيين كلمة مرور متجر ${storeId}؟`)) return
    try {
      await api.resetPassword(storeId)
      setMsg(`تمت إعادة التعيين — كلمة المرور الجديدة: ${storeId}`)
    } catch (e: unknown) {
      setMsg(e instanceof Error ? e.message : 'خطأ')
    }
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
    } catch (e: unknown) {
      setRegError(e instanceof Error ? e.message : 'خطأ')
    } finally {
      setRegLoading(false)
    }
  }

  function logout() { clearAuth(); navigate('/login', { replace: true }) }

  const dbConnected = Boolean(env['DB_CONNECTED'])

  return (
    <div className="min-h-screen bg-background p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-primary rounded-xl flex items-center justify-center">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
          </div>
          <div>
            <h1 className="text-xl font-bold text-foreground">لوحة التحكم الرئيسية</h1>
            <p className="text-xs text-default-400">إدارة جميع المتاجر</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Chip
            size="sm"
            color={dbConnected ? 'success' : 'danger'}
            variant="dot"
          >
            {dbConnected ? 'DB متصل' : 'DB غير متصل'}
          </Chip>
          <Button size="sm" variant="bordered" onPress={onOpen}>
            + تسجيل متجر
          </Button>
          <Button size="sm" variant="bordered" color="warning" isLoading={syncing} onPress={handleForceSync}>
            مزامنة DB
          </Button>
          <Button size="sm" variant="flat" color="danger" onPress={logout}>
            خروج
          </Button>
        </div>
      </div>

      {msg && (
        <div className="mb-4 bg-success/10 border border-success/20 rounded-lg p-3 text-success text-sm">
          {msg}
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {[
          { label: 'المتاجر', value: stores.length, color: 'text-primary' },
          { label: 'إجمالي المنتجات', value: stores.reduce((a, s) => a + s.products_count, 0), color: 'text-success' },
          { label: 'مع إعدادات AI', value: stores.filter(s => s.has_ai_config).length, color: 'text-warning' },
          { label: 'مزامنة اليوم', value: stores.filter(s => s.last_sync !== 'never').length, color: 'text-secondary' },
        ].map(s => (
          <Card key={s.label} className="bg-content1 border border-divider">
            <CardBody className="py-4 px-5">
              <p className="text-xs text-default-400 font-medium">{s.label}</p>
              <p className={`text-3xl font-black mt-1 ${s.color}`}>{s.value}</p>
            </CardBody>
          </Card>
        ))}
      </div>

      {/* Stores table */}
      <Card className="bg-content1 border border-divider">
        <CardHeader className="px-5 py-4">
          <h2 className="font-bold text-base">المتاجر المسجلة</h2>
        </CardHeader>
        <Divider />
        {loading ? (
          <CardBody className="flex items-center justify-center py-16">
            <Spinner size="lg" color="primary" />
          </CardBody>
        ) : (
          <Table
            aria-label="stores"
            classNames={{
              wrapper: 'bg-transparent shadow-none p-0',
              th: 'bg-content2 text-default-400 text-xs font-semibold',
              td: 'py-3',
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
            <TableBody emptyContent="لا يوجد متاجر مسجلة">
              {stores.map(s => (
                <TableRow key={s.store_id} className="hover:bg-content2/50 cursor-pointer">
                  <TableCell onClick={() => navigate(`/store/${s.store_id}`)}>
                    <div className="flex items-center gap-3">
                      <Avatar
                        src={s.store_avatar || undefined}
                        name={s.store_name[0]}
                        size="sm"
                        className="bg-primary/20 text-primary"
                      />
                      <div>
                        <p className="font-semibold text-sm text-foreground">{s.store_name}</p>
                        <p className="text-xs text-default-400">{s.store_id}</p>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <span className="text-sm text-default-300">{s.store_domain || '—'}</span>
                  </TableCell>
                  <TableCell>
                    <span className="font-semibold text-primary">{s.products_count}</span>
                  </TableCell>
                  <TableCell>
                    <Chip size="sm" color={s.has_ai_config ? 'success' : 'default'} variant="flat">
                      {s.has_ai_config ? '✓ مُعدّ' : 'بيئة'}
                    </Chip>
                  </TableCell>
                  <TableCell>
                    <span className="text-xs text-default-400">
                      {s.last_sync === 'never' ? 'لم تتم بعد' : new Date(s.last_sync).toLocaleString('ar-SA')}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Tooltip content="فتح لوحة المتجر">
                        <Button size="sm" variant="flat" color="primary" isIconOnly
                          onPress={() => navigate(`/store/${s.store_id}`)}>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                            <polyline points="15 3 21 3 21 9"/>
                            <line x1="10" y1="14" x2="21" y2="3"/>
                          </svg>
                        </Button>
                      </Tooltip>
                      <Tooltip content="إعادة تعيين كلمة المرور">
                        <Button size="sm" variant="flat" color="warning" isIconOnly
                          onPress={() => handleReset(s.store_id)}>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                            <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                          </svg>
                        </Button>
                      </Tooltip>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      {/* Register store modal */}
      <Modal isOpen={isOpen} onClose={onClose} placement="center">
        <ModalContent className="bg-content1 border border-divider">
          <ModalHeader>تسجيل متجر جديد يدوياً</ModalHeader>
          <ModalBody className="gap-3">
            <Input label="معرف المتجر *" value={regStoreId} onValueChange={setRegStoreId} variant="bordered" classNames={{ inputWrapper: 'border-divider' }} />
            <Input label="Access Token *" value={regToken} onValueChange={setRegToken} variant="bordered" classNames={{ inputWrapper: 'border-divider' }} />
            <Input label="Refresh Token" value={regRefresh} onValueChange={setRegRefresh} variant="bordered" classNames={{ inputWrapper: 'border-divider' }} />
            <Input label="اسم المتجر" value={regName} onValueChange={setRegName} variant="bordered" classNames={{ inputWrapper: 'border-divider' }} />
            {regError && <p className="text-danger text-sm">{regError}</p>}
          </ModalBody>
          <ModalFooter>
            <Button variant="flat" onPress={onClose}>إلغاء</Button>
            <Button color="primary" isLoading={regLoading} onPress={handleRegister}>تسجيل</Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </div>
  )
}
