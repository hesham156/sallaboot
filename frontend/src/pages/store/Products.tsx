import { useEffect, useState } from 'react'
import {
  Card, CardBody, CardHeader,
  Table, TableHeader, TableColumn, TableBody, TableRow, TableCell,
  Button, Chip, Input, Spinner, Pagination, Divider,
} from '@heroui/react'
import { api, Product } from '../../api'

interface Props { storeId: string }

export default function Products({ storeId }: Props) {
  const [products, setProducts] = useState<Product[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [lastSync, setLastSync] = useState('')
  const PER_PAGE = 20

  useEffect(() => { loadProducts() }, [storeId])

  async function loadProducts() {
    setLoading(true)
    try {
      const res = await api.products(storeId)
      setProducts(res.products)
      setTotal(res.total_products)
      setLastSync(res.last_sync)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  async function handleSync() {
    setSyncing(true); setSyncMsg('')
    try {
      const r = await api.sync(storeId)
      setSyncMsg(`✅ تمت المزامنة — ${r.products_count} منتج`)
      loadProducts()
    } catch (e: unknown) {
      setSyncMsg(e instanceof Error ? e.message : 'خطأ')
    } finally { setSyncing(false) }
  }

  const filtered = search
    ? products.filter(p =>
        p.name.toLowerCase().includes(search.toLowerCase()) ||
        String(p.id).includes(search)
      )
    : products

  const pageProducts = filtered.slice((page - 1) * PER_PAGE, page * PER_PAGE)
  const pageCount = Math.ceil(filtered.length / PER_PAGE)

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-foreground">المنتجات</h1>
          <p className="text-sm text-default-400 mt-1">
            {total} منتج — آخر مزامنة: {lastSync === 'never' ? 'لم تتم' : new Date(lastSync).toLocaleString('ar-SA')}
          </p>
        </div>
        <Button color="primary" variant="flat" isLoading={syncing} onPress={handleSync}>
          مزامنة المنتجات
        </Button>
      </div>

      {syncMsg && (
        <div className={`rounded-lg p-3 text-sm border ${
          syncMsg.startsWith('✅') ? 'bg-success/10 border-success/20 text-success' : 'bg-danger/10 border-danger/20 text-danger'
        }`}>
          {syncMsg}
        </div>
      )}

      {/* Search */}
      <Input
        placeholder="بحث بالاسم أو الرقم..."
        value={search}
        onValueChange={v => { setSearch(v); setPage(1) }}
        variant="bordered"
        classNames={{ inputWrapper: 'border-divider bg-content1' }}
        startContent={
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-default-400">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
        }
      />

      {/* Table */}
      <Card className="bg-content1 border border-divider">
        {loading ? (
          <CardBody className="flex items-center justify-center py-16">
            <Spinner size="lg" color="primary" />
          </CardBody>
        ) : (
          <Table
            aria-label="products"
            classNames={{
              wrapper: 'bg-transparent shadow-none',
              th: 'bg-content2 text-default-400 text-xs',
              td: 'py-3',
            }}
            bottomContent={
              pageCount > 1 ? (
                <div className="flex justify-center py-2">
                  <Pagination
                    total={pageCount}
                    page={page}
                    onChange={setPage}
                    color="primary"
                    variant="flat"
                    size="sm"
                  />
                </div>
              ) : null
            }
          >
            <TableHeader>
              <TableColumn>المنتج</TableColumn>
              <TableColumn>السعر</TableColumn>
              <TableColumn>الحالة</TableColumn>
              <TableColumn>الكمية</TableColumn>
            </TableHeader>
            <TableBody emptyContent="لا توجد منتجات">
              {pageProducts.map(p => (
                <TableRow key={p.id}>
                  <TableCell>
                    <div className="flex items-center gap-3">
                      {p.image && (
                        <img
                          src={p.image}
                          alt={p.name}
                          className="w-10 h-10 rounded-lg object-cover bg-content2"
                        />
                      )}
                      <div>
                        <p className="text-sm font-medium text-foreground">{p.name}</p>
                        <p className="text-xs text-default-400">#{p.id}</p>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <span className="font-semibold text-primary text-sm">
                      {p.sale_price
                        ? <><s className="text-default-400 text-xs">{p.price}</s> {p.sale_price}</>
                        : p.price
                      } {p.currency}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="sm"
                      color={p.status === 'sale' ? 'success' : p.status === 'hidden' ? 'default' : 'warning'}
                      variant="flat"
                    >
                      {p.status === 'sale' ? 'متوفر' : p.status === 'hidden' ? 'مخفي' : 'نفد'}
                    </Chip>
                  </TableCell>
                  <TableCell>
                    <span className="text-sm text-default-300">
                      {p.unlimited_quantity ? '∞' : p.quantity}
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
