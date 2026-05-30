import { useEffect, useState } from 'react'
import {
  Card, CardBody,
  Table, TableHeader, TableColumn, TableBody, TableRow, TableCell,
  Button, Chip, Spinner,
} from '@heroui/react'
import { api, AbandonedCart } from '../../api'

interface Props { storeId: string }

export default function AbandonedCarts({ storeId }: Props) {
  const [carts, setCarts] = useState<AbandonedCart[]>([])
  const [loading, setLoading] = useState(true)
  const [recovering, setRecovering] = useState<string | null>(null)

  useEffect(() => { loadCarts() }, [storeId])

  async function loadCarts() {
    setLoading(true)
    try {
      const res = await api.abandonedCarts(storeId)
      setCarts(res.carts)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  async function recover(cartId: string) {
    setRecovering(cartId)
    try {
      await api.recoverCart(storeId, cartId)
      setCarts(prev => prev.map(c => c.id === cartId ? { ...c, recovered: true } : c))
    } finally { setRecovering(null) }
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-foreground">السلات المتروكة</h1>
          <p className="text-sm text-default-400 mt-1">
            {carts.length} سلة — {carts.filter(c => !c.recovered).length} قيد الانتظار
          </p>
        </div>
        <Button size="sm" variant="flat" onPress={loadCarts}>تحديث</Button>
      </div>

      <Card className="bg-content1 border border-divider">
        {loading ? (
          <CardBody className="flex items-center justify-center py-16">
            <Spinner size="lg" color="primary" />
          </CardBody>
        ) : (
          <Table
            aria-label="abandoned-carts"
            classNames={{
              wrapper: 'bg-transparent shadow-none',
              th: 'bg-content2 text-default-400 text-xs',
              td: 'py-3',
            }}
          >
            <TableHeader>
              <TableColumn>العميل</TableColumn>
              <TableColumn>الإجمالي</TableColumn>
              <TableColumn>المنتجات</TableColumn>
              <TableColumn>الوقت</TableColumn>
              <TableColumn>الحالة</TableColumn>
              <TableColumn>إجراء</TableColumn>
            </TableHeader>
            <TableBody emptyContent="لا توجد سلات متروكة">
              {carts.map(c => (
                <TableRow key={c.id}>
                  <TableCell>
                    <div>
                      <p className="font-semibold text-sm text-foreground">{c.customer_name}</p>
                      <p className="text-xs text-default-400">{c.customer_phone}</p>
                    </div>
                  </TableCell>
                  <TableCell>
                    <span className="font-bold text-primary text-sm">
                      {c.total} {c.currency}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className="text-sm text-default-300">{c.items_count} منتج</span>
                  </TableCell>
                  <TableCell>
                    <span className="text-xs text-default-400">
                      {new Date(c.ts).toLocaleString('ar-SA')}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="sm"
                      color={c.recovered ? 'success' : 'warning'}
                      variant="flat"
                    >
                      {c.recovered ? 'تم الاسترداد' : 'قيد الانتظار'}
                    </Chip>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      {!c.recovered && (
                        <Button
                          size="sm"
                          color="success"
                          variant="flat"
                          isLoading={recovering === c.id}
                          onPress={() => recover(c.id)}
                        >
                          استرداد
                        </Button>
                      )}
                      {c.checkout_url && (
                        <Button
                          size="sm"
                          variant="flat"
                          as="a"
                          href={c.checkout_url}
                          target="_blank"
                        >
                          رابط
                        </Button>
                      )}
                    </div>
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
