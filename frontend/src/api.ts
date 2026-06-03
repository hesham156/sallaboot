// ── Auth token management ──────────────────────────────────────────────────────

export function getToken(): string {
  return localStorage.getItem('admin_token') || ''
}
export function setToken(t: string) {
  localStorage.setItem('admin_token', t)
}
export function getStoreId(): string {
  return localStorage.getItem('admin_store_id') || ''
}
export function setStoreId(id: string) {
  localStorage.setItem('admin_store_id', id)
}
export function getIsSuper(): boolean {
  return localStorage.getItem('admin_is_super') === 'true'
}
export function setIsSuper(v: boolean) {
  localStorage.setItem('admin_is_super', String(v))
}
export function clearAuth() {
  localStorage.removeItem('admin_token')
  localStorage.removeItem('admin_store_id')
  localStorage.removeItem('admin_is_super')
}

// ── Core fetch wrapper ─────────────────────────────────────────────────────────

async function req<T>(
  method: string,
  url: string,
  body?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extraHeaders,
  }
  const res = await fetch(url, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

const get  = <T>(url: string) => req<T>('GET', url)
const post = <T>(url: string, body?: unknown) => req<T>('POST', url, body)
const put  = <T>(url: string, body?: unknown) => req<T>('PUT', url, body)

// ── Auth ───────────────────────────────────────────────────────────────────────

export const api = {
  // Login — super admin (email + password)
  superLogin: (email: string, password: string) =>
    post<{ token: string; store_id: string; is_super: boolean }>(
      '/admin/auth/login',
      { email, password },
    ),

  // Login — store owner (store_id + password)
  storeLogin: (storeId: string, password: string) =>
    post<{ token: string; store_id: string; store_name: string }>(
      `/admin/${storeId}/auth/login`,
      { password },
    ),
  verifyToken: (storeId: string) =>
    get<{ ok: boolean; store_id: string; is_super: boolean }>(
      `/admin/${storeId}/auth/verify`,
    ),

  // Stores
  listStores: () =>
    get<{ stores: StoreInfo[] }>('/admin/stores'),

  // Single store info — accessible with store token (no super needed)
  getStoreInfo: (storeId: string) =>
    get<StoreInfo>(`/admin/${storeId}/info`),

  // Conversations
  listConversations: (storeId: string, limit = 100, offset = 0) =>
    get<{ total: number; conversations: ConvSummary[] }>(
      `/admin/${storeId}/conversations?limit=${limit}&offset=${offset}`,
    ),
  getConversation: (storeId: string, sessionId: string) =>
    get<Conversation>(`/admin/${storeId}/conversations/${sessionId}`),
  adminReply: (storeId: string, sessionId: string, message: string) =>
    post(`/admin/${storeId}/conversations/${sessionId}/reply`, { message }),
  takeover: (storeId: string, sessionId: string) =>
    post(`/admin/${storeId}/conversations/${sessionId}/takeover`),
  handback: (storeId: string, sessionId: string) =>
    post(`/admin/${storeId}/conversations/${sessionId}/handback`),

  // Bot toggle
  botStatus: (storeId: string) =>
    get<{ bot_globally_enabled: boolean }>(`/admin/${storeId}/bot/status`),
  botToggle: (storeId: string, enabled: boolean) =>
    post<{ bot_globally_enabled: boolean }>(
      `/admin/${storeId}/bot/toggle`,
      { enabled },
    ),

  // Products
  sync: (storeId: string) =>
    post<{ products_count: number; last_sync: string }>(
      `/admin/${storeId}/sync`,
    ),
  products: (storeId: string, limit = 500, offset = 0) =>
    get<{ products: Product[]; total_products: number; last_sync: string }>(
      `/admin/${storeId}/products?limit=${limit}&offset=${offset}`,
    ),

  // Analytics
  analytics: (storeId: string) =>
    get<Analytics>(`/admin/${storeId}/analytics`),
  insights: (storeId: string) =>
    get<ConversationInsights>(`/admin/${storeId}/analytics/insights`),
  roi: (storeId: string, days = 30) =>
    get<ROIData>(`/admin/${storeId}/analytics/roi?days=${days}`),
  weekly: (storeId: string) =>
    get<WeeklyReport>(`/admin/${storeId}/analytics/weekly`),

  // AI settings
  getAI: (storeId: string) =>
    get<AIConfig>(`/admin/${storeId}/settings/ai`),
  setAI: (storeId: string, cfg: Partial<AIConfig>) =>
    put(`/admin/${storeId}/settings/ai`, cfg),

  // Pricing calculator settings
  getPricing: (storeId: string) =>
    get<PricingConfig>(`/admin/${storeId}/settings/pricing`),
  setPricing: (storeId: string, cfg: PricingConfig) =>
    put(`/admin/${storeId}/settings/pricing`, cfg),
  testPricing: (storeId: string, payload: Record<string, unknown>) =>
    post<Record<string, unknown>>(`/admin/${storeId}/settings/pricing/test`, payload),

  // AI brain (store knowledge / memory)
  getBrain: (storeId: string) =>
    get<BrainData>(`/admin/${storeId}/settings/brain`),
  setBrain: (storeId: string, custom_knowledge: string) =>
    put(`/admin/${storeId}/settings/brain`, { custom_knowledge }),
  retrainBrain: (storeId: string) =>
    post<{ products_synced: number; categories: number; overview: BrainOverview; message: string }>(
      `/admin/${storeId}/settings/brain/retrain`,
    ),

  // Bot training (admin's instructions, FAQs, uploaded files)
  listTraining: (storeId: string) =>
    get<{ count: number; items: TrainingEntry[] }>(
      `/admin/${storeId}/settings/training`,
    ),
  addTextTraining: (storeId: string, payload: { kind: 'instruction' | 'faq'; title: string; content: string }) =>
    post<{ id: number; message: string }>(
      `/admin/${storeId}/settings/training/text`, payload,
    ),
  uploadTrainingFile: async (storeId: string, file: File, title = ''): Promise<{ id: number; filename: string; size_chars: number; warning?: string; message: string }> => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('title', title)
    const token = getToken()
    const res = await fetch(`/admin/${storeId}/settings/training/file`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: fd,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    return res.json()
  },
  toggleTraining: (storeId: string, id: number, enabled: boolean) =>
    req<{ status: string }>('PATCH', `/admin/${storeId}/settings/training/${id}`, { enabled }),
  deleteTraining: (storeId: string, id: number) =>
    req<{ status: string }>('DELETE', `/admin/${storeId}/settings/training/${id}`),

  // Password
  changePassword: (storeId: string, current_password: string, new_password: string) =>
    put(`/admin/${storeId}/settings/password`, { current_password, new_password }),

  // Token status
  tokenStatus: (storeId: string) =>
    get<TokenStatus>(`/admin/${storeId}/settings/token-status`),
  refreshToken: (storeId: string) =>
    post<TokenStatus>(`/admin/${storeId}/settings/token-refresh`),

  // Orders
  orders: (storeId: string, page = 1, perPage = 20) =>
    get<{ data: Order[]; pagination?: unknown }>(
      `/admin/${storeId}/orders?page=${page}&per_page=${perPage}`,
    ),

  // Abandoned carts
  abandonedCarts: (storeId: string, source = 'cache') =>
    get<{ carts: AbandonedCart[]; count: number }>(
      `/admin/${storeId}/abandoned-carts?source=${source}`,
    ),
  recoverCart: (storeId: string, cartId: string) =>
    post(`/admin/${storeId}/abandoned-carts/${cartId}/recover`),

  // Webhook log
  webhookLog: (storeId: string) =>
    get<{ events: WebhookEvent[] }>(`/admin/${storeId}/webhooks/log`),

  // Debug
  debug: (storeId: string) =>
    get<DebugInfo>(`/admin/${storeId}/debug`),
  testOrder: (storeId: string) =>
    post<{
      ok: boolean; stage?: string; error?: string
      product_created?: boolean; product_id?: number
      order_created?: boolean; order_id?: number; payment_url?: string
      message?: string
    }>(`/admin/${storeId}/debug/test-order`),

  // Env check
  envCheck: () =>
    get<Record<string, unknown>>('/env-check'),

  // Force DB sync
  forceDbSync: () =>
    post<{ saved: number; total: number; message: string }>('/admin/force-db-sync'),

  // DB round-trip diagnostic (super-admin)
  dbTest: () =>
    get<{
      ok: boolean
      connected: boolean
      write_ok: boolean
      read_ok: boolean
      delete_ok: boolean
      store_count: number
      error: string
      env_database_url_set: boolean
      in_memory_stores: number
    }>('/admin/db-test'),

  // Registry vs DB — find stores that exist in DB but not loaded into memory
  registryVsDb: () =>
    get<{
      db_connected: boolean
      in_db: number
      in_memory: number
      only_in_db: string[]
      only_in_memory: string[]
      in_both: string[]
      db_rows: Array<{ store_id: string; store_name: string; has_token: boolean; has_refresh: boolean; has_ai_config: boolean; updated_at: string }>
      memory_rows: StoreInfo[]
    }>('/admin/registry-vs-db'),

  // Force reload registry from DB (recovers stores skipped at startup)
  reloadFromDb: () =>
    post<{ before: number; after: number; loaded: number; message: string }>('/admin/reload-from-db'),

  // Super-admin: reset store password
  resetPassword: (storeId: string) =>
    put(`/admin/stores/${storeId}/reset-password`),
}

// ── Types ──────────────────────────────────────────────────────────────────────

export interface StoreInfo {
  store_id: string
  store_name: string
  store_domain: string
  store_avatar: string
  connected_at: string
  products_count: number
  last_sync: string
  last_sync_errors: string[]
  has_ai_config: boolean
}

export interface ConvSummary {
  session_id: string
  store_id?: string
  created_at: string
  last_activity: string
  messages_count: number
  user_messages_count?: number
  // Backend returns the last message as a full object (kept for legacy admin.html compat)
  last_message: Message | null
  bot_enabled: boolean
  unread: boolean
  rating?: number
}

export interface Message {
  role: 'user' | 'assistant' | 'admin'
  content: string
  ts: string
}

export interface Conversation extends ConvSummary {
  messages: Message[]
  cart?: unknown[]
  // Backend field name is customer_info, not customer
  customer_info?: { name?: string; phone?: string; email?: string }
}

export interface Product {
  id: string | number
  name: string
  price: string | number
  sale_price?: string | number
  currency: string
  status: string
  quantity: number
  unlimited_quantity?: boolean
  image?: string
  url?: string
  categories?: string[]
  description?: string
}

export interface Analytics {
  conversations: {
    total: number
    today: number
    this_week: number
    bot_handled: number
    admin_takeover: number
    avg_messages: number
    daily_counts: { date: string; count: number }[]
    hourly_distribution: number[]
  }
  messages: { total: number; user: number; bot: number; admin: number }
  abandoned_carts: { total: number; recovered: number; pending: number; recovery_rate: number }
  products: { count: number; last_sync: string }
  ratings: { count: number; avg: number; distribution: number[] }
}

// ── Conversation Insights ─────────────────────────────────────────────────

export interface TopicItem {
  id: string
  label: string
  icon: string
  count: number
  percent: number
  examples: string[]
}

export interface NonPurchaseItem {
  id: string
  label: string
  icon: string
  count: number
  percent: number
}

export interface AtRiskCustomer {
  session_id: string
  signal: string
  last_message: string
  last_role: string
  ts: string
  customer_name: string
  customer_phone: string
  rating: number | null
}

export interface ConversationInsights {
  top_questions: TopicItem[]
  non_purchase: NonPurchaseItem[]
  at_risk_customers: AtRiskCustomer[]
  sentiment_summary: { happy: number; neutral: number; angry: number; total: number }
  conversion: {
    total_convs: number
    with_checkout: number
    without_checkout: number
    conversion_rate: number
  }
}

export interface WeeklyReport {
  currency: string
  revenue: number
  revenue_delta: number
  orders: number
  orders_delta: number
  conversations: number
  conv_delta: number
  avg_rating: number
  top_topic: string
}

export interface ROIData {
  days: number
  currency: string
  revenue: number
  orders: number
  avg_order: number
  revenue_all: number
  orders_all: number
  conversations: number
  messages_handled: number
  hours_saved: number
  carts_recovered: number
}

export interface AIConfig {
  groq_api_key: string
  anthropic_api_key: string
  openai_api_key: string
  ai_model: string
  bot_name: string
  provider: 'groq' | 'anthropic' | 'openai' | 'env'
  store_type: 'printing' | 'general'
  whatsapp_enabled?: boolean
  whatsapp_phone_id?: string
  whatsapp_token?: string
  whatsapp_webhook?: string
  whatsapp_verify_token?: string
}

// ── AI Brain / store knowledge ─────────────────────────────────────────────

export interface BrainOverview {
  total_products: number
  available_products: number
  categories: number
  currency: string
  min_price: number | null
  max_price: number | null
  avg_price: number | null
  top_categories: { name: string; count: number }[]
  last_sync: string
}

export interface StoreInfoSnapshot {
  id?: number
  name?: string
  entity?: string
  email?: string
  avatar?: string
  plan?: string
  type?: string
  status?: string
  verified?: boolean
  currency?: string
  domain?: string
  description?: string
  licenses?: { tax_number?: string; commercial_number?: string; freelance_number?: string }
  social?: {
    telegram?: string; twitter?: string; facebook?: string; maroof?: string
    youtube?: string; snapchat?: string; whatsapp?: string; instagram?: string
    appstore_link?: string; googleplay_link?: string
  }
}

export interface TrainingEntry {
  id: number
  kind: 'instruction' | 'faq' | 'file' | 'lesson'
  title: string
  content: string
  file_id: string
  file_name: string
  size_chars: number
  enabled: boolean
  created_at: string
}

export interface ShippingCompany {
  id?: number
  name: string
  slug?: string
  activation_type?: 'manual' | 'api' | string
}

export interface SallaBrand   { id?: number; name: string; logo?: string; url?: string }
export interface SallaOffer   { id?: number; name: string; message?: string; status?: string; end_date?: string }
export interface SallaBranch  { id?: number; name: string; city?: string; address?: string; phone?: string }
export interface SallaPayment { id?: number; name: string; slug?: string; logo?: string }

export interface BrainData {
  overview: BrainOverview
  store_info?: StoreInfoSnapshot
  shipping_companies?: ShippingCompany[]
  brands?: SallaBrand[]
  special_offers?: SallaOffer[]
  branches?: SallaBranch[]
  payment_methods?: SallaPayment[]
  knowledge_chars: number
  knowledge_budget: number
  custom_knowledge: string
  knowledge_preview: string
}

// ── Printing calculator config ─────────────────────────────────────────────

export interface PaperType { name: string; price: number; active: boolean }
export interface SheetSize { name: string; width: number; height: number }
export interface AddonItem { name: string; price: number }
export interface DiscountRule { min: number; percent: number }
export interface TierRule { min: number; price: number }

export interface PricingConfig {
  // General
  tax_rate: number
  profit_margin: number

  // Roll
  roll_enabled: boolean
  roll_unit_price: number
  default_roll_width: number
  roll_discounts: DiscountRule[]

  // Digital
  digital_enabled: boolean
  digital_paper_types: PaperType[]
  digital_sheet_sizes: SheetSize[]
  digital_addons: AddonItem[]
  digital_discounts: DiscountRule[]
  foil_mold_price_per_cm2: number
  foil_min_mold_price: number
  foil_stamping_unit_price: number

  // Offset
  offset_enabled: boolean
  offset_fixed_width: number
  offset_fixed_height: number
  offset_paper_types: PaperType[]
  offset_discounts: DiscountRule[]
  offset_cutting_normal: number
  offset_cutting_diecut: number
  offset_folding_per_1000: number
  offset_punching_per_1000: number

  // UV DTF
  uvdtf_enabled: boolean
  uvdtf_unit_price: number
  uvdtf_roll_width: number
  uvdtf_tiers: TierRule[]
}

export interface TokenStatus {
  // Backend fields (salla_oauth.get_token_status + endpoint enrichment)
  status: 'ok' | 'warning' | 'critical' | 'expired' | 'unknown'
  days_remaining: number | null
  expires_at: string
  message: string
  store_name?: string
  connected_at?: string
  has_refresh?: boolean
}

export interface Order {
  id: number
  reference_id: string
  status: { name: string; slug: string }
  total: { amount: string; currency: string }
  date: { date: string }
  customer?: { first_name?: string; last_name?: string }
}

export interface AbandonedCart {
  id: string
  ts: string
  customer_name: string
  customer_phone: string
  total: string
  currency: string
  items_count: number
  checkout_url: string
  recovered: boolean
}

export interface WebhookEvent {
  event: string
  status: string
  detail: string
  ts: string
}

export interface DebugInfo {
  store_id: string
  store_name: string
  token_present: boolean
  token_preview: string
  cached_products: number
  last_sync: string
  last_sync_errors: string[]
  salla_api_test?: { status_code?: number; body_preview?: string; error?: string }
}
