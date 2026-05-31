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
  // Login
  superLogin: (password: string) =>
    post<{ token: string; store_id: string; is_super: boolean }>(
      '/admin/auth/login',
      { password },
    ),
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

  // AI settings
  getAI: (storeId: string) =>
    get<AIConfig>(`/admin/${storeId}/settings/ai`),
  setAI: (storeId: string, cfg: Partial<AIConfig>) =>
    put(`/admin/${storeId}/settings/ai`, cfg),

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

  // Env check
  envCheck: () =>
    get<Record<string, unknown>>('/env-check'),

  // Force DB sync
  forceDbSync: () =>
    post<{ saved: number; total: number; message: string }>('/admin/force-db-sync'),

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
  customer?: { name?: string; phone?: string; email?: string }
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

export interface AIConfig {
  groq_api_key: string
  anthropic_api_key: string
  openai_api_key: string
  ai_model: string
  bot_name: string
  provider: 'groq' | 'anthropic' | 'openai' | 'env'
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
