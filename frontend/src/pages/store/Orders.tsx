import { useEffect, useState } from 'react'
import {
  Card, CardBody,
  Table, TableHeader, TableColumn, TableBody, TableRow, TableCell,
  Button, Chip, Input, Spinner, Pagination,
} from '@heroui/react'
import { api, Order } from '../../api'
import { PageHeader } from '../../components/ui'

interface Props { storeId: string }

const STATUS_COLORS: Record<string, 'success'|'warning'|'danger'|'default'|'primary'> = {
  completed:   'success',
  processing:  'primary',
  in_shipping: 'primary',
  pending:     'warning',
  under_review:'warning',
  cancelled:   'danger',
  refunded:    'danger',
  on_hold:     'default',
}

export default function Orders({ storeId }: Props) {
  const [orders, setOrders] = useState<Order[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')

  useEffect(() => { loadOrders() }, [storeId, page])

  async function loadOrders() {
    setLoading(true)
    try {
      const res = await api.orders(storeId, page)
      setOrders(res.data || [])
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  const filtered = search
    ? orders.filter(o =>
        String(o.id).includes(search) ||
        o.reference_id?.includes(search) ||
        `${o.customer?.first_name} ${o.customer?.last_name}`.includes(search)
      )
    : orders

  return (
    <div className="p-6 space-y-4">
      <PageHeader
        title="الطلبات"
        subtitle="طلبات المتجر مع حالتها وتفاصيل العميل"
        icon="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z"
        actions={<Button size="sm" variant="flat" onPress={loadOrders}>تحديث</Button>}
      />


      <Input
        placeholder="بحث برقم الطلب أو المرجع..."
        value={search}
        onValueChange={setSearch}
        variant="bordered"
        classNames={{ inputWrapper: 'border-divider bg-content1' }}
        startContent={
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-default-400">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
        }
      />

      <Card className="bg-content1 border border-divider">
        {loading ? (
          <CardBody className="flex items-center justify-center py-16">
            <Spinner size="lg" color="primary" />
          </CardBody>
        ) : (
          <Table
            aria-label="orders"
            classNames={{
              wrapper: 'bg-transparent shadow-none',
              th: 'bg-content2 text-default-400 text-xs',
              td: 'py-3',
            }}
            bottomContent={
              <div className="flex justify-center py-2">
                <div className="flex gap-2">
                  <Button size="sm" variant="flat" isDisabled={page === 1} onPress={() => setPage(p => p - 1)}>السابق</Button>
                  <Button size="sm" variant="flat" onPress={() => setPage(p => p + 1)}>التالي</Button>
                </div>
              </div>
            }
          >
            <TableHeader>
              <TableColumn>رقم الطلب</TableColumn>
              <TableColumn>الحالة</TableColumn>
              <TableColumn>الإجمالي</TableColumn>
              <TableColumn>التاريخ</TableColumn>
            </TableHeader>
            <TableBody emptyContent="لا توجد طلبات">
              {filtered.map(o => (
                <TableRow key={o.id}>
                  <TableCell>
                    <div>
                      <p className="font-semibold text-sm text-foreground">#{o.reference_id || o.id}</p>
                      {o.customer && (
                        <p className="text-xs text-default-400">
                          {o.customer.first_name} {o.customer.last_name}
                        </p>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="sm"
                      color={STATUS_COLORS[o.status?.slug] || 'default'}
                      variant="flat"
                    >
                      {o.status?.name || o.status?.slug}
                    </Chip>
                  </TableCell>
                  <TableCell>
                    <span className="font-bold text-primary text-sm">
                      {o.total?.amount} {o.total?.currency}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className="text-xs text-default-400">
                      {o.date?.date ? new Date(o.date.date).toLocaleDateString('ar-SA') : '—'}
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  )
}
