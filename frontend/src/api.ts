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

// Employee identity carried in the token, when the user logged in as an employee
export interface SessionEmployee {
  id:   number
  name: string
  role: string
}
export function getEmployee(): SessionEmployee | null {
  const raw = localStorage.getItem('admin_employee')
  if (!raw) return null
  try { return JSON.parse(raw) as SessionEmployee } catch { return null }
}
export function setEmployee(e: SessionEmployee | null) {
  if (e) localStorage.setItem('admin_employee', JSON.stringify(e))
  else   localStorage.removeItem('admin_employee')
}

export function clearAuth() {
  localStorage.removeItem('admin_token')
  localStorage.removeItem('admin_store_id')
  localStorage.removeItem('admin_is_super')
  localStorage.removeItem('admin_employee')
}

// ── Core fetch wrapper ─────────────────────────────────────────────────────────

/**
 * Thrown by req() on any non-2xx response. Carries the HTTP status so
 * callers can react differently to 401 (kick to login), 403 (no-access
 * page), 429 (back off), etc., without parsing the message text.
 *
 * The default toString preserves the Arabic detail message so existing
 * `e.message`-based error displays still work — this class is additive,
 * not breaking.
 */
export class ApiError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`)
    this.name   = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

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
    throw new ApiError(res.status, err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

const get  = <T>(url: string) => req<T>('GET', url)
const post = <T>(url: string, body?: unknown) => req<T>('POST', url, body)
const put  = <T>(url: string, body?: unknown) => req<T>('PUT', url, body)

// ── Auth ───────────────────────────────────────────────────────────────────────

export const api = {
  // Unified email/password login. Backend figures out which kind of
  // account the email belongs to (super → employee → store owner) and
  // returns a uniform response.
  login: (email: string, password: string) =>
    post<{
      token:      string
      store_id:   string
      store_name: string
      is_super:   boolean
      employee:   SessionEmployee | null
    }>('/auth/login', { email, password }),

  // Legacy login endpoints — kept so older clients still work but the
  // SPA itself uses `login()` above.
  superLogin: (email: string, password: string) =>
    post<{ token: string; store_id: string; is_super: boolean }>(
      '/admin/auth/login',
      { email, password },
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

  // Single store info — accessible with store token (no super needed)
  getStoreInfo: (storeId: string) =>
    get<StoreInfo>(`/admin/${storeId}/info`),

  // Conversations
  listConversations: (storeId: string, limit = 100, offset = 0) =>
    get<{ total: number; conversations: ConvSummary[] }>(
      `/admin/${storeId}/conversations?limit=${limit}&offset=${offset}`,
    ),

  // Realtime stream ticket — exchanged for a short-lived token because
  // EventSource can't send custom headers. POST is authenticated by the
  // current bearer; the returned ticket is consumed by openAdminStream.
  streamTicket: (storeId: string, reason?: string) => {
    const qs = reason ? `?reason=${encodeURIComponent(reason)}` : ''
    return post<{ ticket: string; ttl_seconds: number }>(
      `/admin/${storeId}/stream/ticket${qs}`,
    )
  },
  getConversation: (storeId: string, sessionId: string, reason?: string) => {
    const qs = reason ? `?reason=${encodeURIComponent(reason)}` : ''
    return get<Conversation>(`/admin/${storeId}/conversations/${sessionId}${qs}`)
  },
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
      throw new ApiError(res.status, err.detail || `HTTP ${res.status}`)
    }
    return res.json()
  },
  toggleTraining: (storeId: string, id: number, enabled: boolean) =>
    req<{ status: string }>('PATCH', `/admin/${storeId}/settings/training/${id}`, { enabled }),
  deleteTraining: (storeId: string, id: number) =>
    req<{ status: string }>('DELETE', `/admin/${storeId}/settings/training/${id}`),

  // Notifications
  getNotifications: (storeId: string) =>
    get<NotificationSettings>(`/admin/${storeId}/settings/notifications`),
  setNotifications: (storeId: string, s: NotificationSettings) =>
    put<{ status: string; message: string }>(`/admin/${storeId}/settings/notifications`, s),
  testNotification: (storeId: string) =>
    post<{ status: string; message: string }>(`/admin/${storeId}/settings/notifications/test`),

  // WhatsApp Events
  getWaEvents: (storeId: string) =>
    get<{ events: Record<string, { enabled: boolean; template: string }> }>(`/admin/${storeId}/settings/whatsapp-events`),
  setWaEvent: (storeId: string, eventKey: string, body: { enabled?: boolean; template?: string }) =>
    put<{ status: string }>(`/admin/${storeId}/settings/whatsapp-events/${eventKey}`, body),
  testWaEvent: (storeId: string, eventKey: string, testPhone?: string) =>
    post<{ status: string; message: string }>(`/admin/${storeId}/settings/whatsapp-events/${eventKey}/test`, { test_phone: testPhone || '' }),

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

  // Super-admin: re-seed the sallabot demo store's custom_knowledge
  // from backend/data/sallabot_knowledge.md. Used after editing the
  // markdown file + redeploying — bootstrap only seeds on first install
  // so file changes need an explicit reload to override UI edits.
  reloadSallabotKnowledge: () =>
    post<{ status: string; loaded: number; file: string; message: string }>(
      '/admin/sallabot/reload-knowledge',
    ),

  // Super-admin: backfill owner_email for stores installed before the
  // unified login shipped. Iterates registered stores, calls Salla
  // /oauth2/user/info with the stored access_token, saves the returned
  // email so the merchant can sign in via email/password.
  backfillOwnerEmails: () =>
    post<{
      filled:      number
      skipped:     number
      failed:      number
      filled_rows: Array<{ store_id: string; email: string }>
      failed_rows: Array<{ store_id: string; reason: string }>
      message:     string
    }>('/admin/backfill-owner-emails'),

  // Super-admin: reset store password
  resetPassword: (storeId: string) =>
    put(`/admin/stores/${storeId}/reset-password`),

  // ── Employees (per-store agents) ─────────────────────────────────────────
  employeeLogin: (storeId: string, email: string, password: string) =>
    post<{
      token: string
      store_id: string
      store_name: string
      employee: SessionEmployee
    }>(`/admin/${storeId}/auth/employee-login`, { email, password }),

  listEmployees: (storeId: string) =>
    get<{ employees: Employee[]; count: number }>(`/admin/${storeId}/employees`),

  employeesRatings: (storeId: string) =>
    get<EmployeesRatingsResponse>(`/admin/${storeId}/employees/ratings`),

  createEmployee: (storeId: string, payload: EmployeeCreateInput) =>
    post<{ id: number; name: string; email: string; role: string }>(
      `/admin/${storeId}/employees`, payload,
    ),

  updateEmployee: (storeId: string, employeeId: number, payload: EmployeeUpdateInput) =>
    req<{ status: string }>('PATCH', `/admin/${storeId}/employees/${employeeId}`, payload),

  deleteEmployee: (storeId: string, employeeId: number) =>
    req<{ status: string }>('DELETE', `/admin/${storeId}/employees/${employeeId}`),

  // End a conversation with farewell + CSAT survey
  endConversation: (storeId: string, sessionId: string, payload?: { farewell?: string; skip_csat?: boolean }) =>
    post<{ status: string; session_id: string; messages: Message[] }>(
      `/admin/${storeId}/conversations/${sessionId}/end`,
      payload || {},
    ),

  // Support-access grants — owner controls super JIT into the dashboard.
  // GET returns active grant + history; POST creates; DELETE revokes.
  // Both owner and super can READ (super needs to know if access exists);
  // only owner can mutate.
  supportAccessStatus: (storeId: string) =>
    get<{ active: SupportAccessGrant | null; history: SupportAccessGrant[] }>(
      `/admin/${storeId}/support-access`,
    ),
  supportAccessGrant: (storeId: string, payload: { duration_minutes: number; note?: string }) =>
    post<SupportAccessGrant>(`/admin/${storeId}/support-access`, payload),
  supportAccessRevoke: (storeId: string, grantId: number) =>
    req<{ status: string }>('DELETE', `/admin/${storeId}/support-access/${grantId}`),

  // Super-admin: platform operations snapshot
  platformOps: () =>
    get<PlatformOpsSnapshot>('/admin/platform-ops'),

  // Audit log readers. Super-admin gets the global view (cross-store);
  // store-scoped owners/managers get only their own store's actions.
  auditLogGlobal: (params: { limit?: number; offset?: number; action?: string; store_id?: string } = {}) => {
    const q = new URLSearchParams()
    if (params.limit  !== undefined) q.set('limit',  String(params.limit))
    if (params.offset !== undefined) q.set('offset', String(params.offset))
    if (params.action)               q.set('action', params.action)
    if (params.store_id)             q.set('store_id', params.store_id)
    const qs = q.toString()
    return get<{ count: number; rows: AuditRow[] }>(`/admin/audit-log${qs ? '?' + qs : ''}`)
  },
  auditLogStore: (storeId: string, params: { limit?: number; offset?: number; action?: string } = {}) => {
    const q = new URLSearchParams()
    if (params.limit  !== undefined) q.set('limit',  String(params.limit))
    if (params.offset !== undefined) q.set('offset', String(params.offset))
    if (params.action)               q.set('action', params.action)
    const qs = q.toString()
    return get<{ count: number; rows: AuditRow[] }>(`/admin/${storeId}/audit-log${qs ? '?' + qs : ''}`)
  },

  // ── LLM usage + daily budget (circuit breaker) ─────────────────────────
  // GET returns today's totals + N-day history + active budget. PUT lets
  // the store owner adjust their daily cap. Setting 0 disables the breaker
  // entirely — but the backend only accepts that from a super admin token.
  getLlmUsage: (storeId: string, days = 7) =>
    get<LlmUsageResponse>(`/admin/${storeId}/llm-usage?days=${days}`),
  setLlmBudget: (storeId: string, dailyTokenBudget: number | null) =>
    put<{ status: string; daily_token_budget: number | null; effective_budget: number }>(
      `/admin/${storeId}/llm-budget`,
      { daily_token_budget: dailyTokenBudget },
    ),
}

// ── Types ──────────────────────────────────────────────────────────────────────

export interface StoreInfo {
  store_id: string
  store_name: string
  store_domain: string
  store_avatar: string
  connected_at: string
  /** Salla owner email — empty until backfilled or re-installed. */
  owner_email?: string
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
  // Channel the conversation arrived on. Absent on legacy rows.
  channel?: 'widget' | 'whatsapp'
}

export interface CsatOption { value: number; label: string }
export interface MessageMeta {
  kind?: 'csat'
  target_agent_id?: number | null
  target_agent_name?: string
  question?: string
  options?: CsatOption[]
}
export interface Message {
  role: 'user' | 'assistant' | 'admin'
  content: string
  ts: string
  employee_name?: string
  employee_id?: number
  meta?: MessageMeta
}

export interface Employee {
  id: number
  store_id: string
  name: string
  email: string
  role: string             // 'agent' | 'manager'
  active: boolean
  created_at: string
}

export interface EmployeeCreateInput {
  name: string
  email: string
  password: string
  role?: string
  active?: boolean
}

export interface EmployeeUpdateInput {
  name?: string
  email?: string
  password?: string
  role?: string
  active?: boolean
}

export interface EmployeeRatingEntry {
  session_id:    string
  rating:        number
  comment:       string
  rated_at:      string
  customer_name: string
}

export interface EmployeeRatingStats {
  employee_id:  number
  name:         string
  email:        string
  role:         string
  active:       boolean
  count:        number
  avg:          number
  distribution: number[]   // length 5: index 0 = rating 1, … 4 = rating 5
  recent:       EmployeeRatingEntry[]
}

export interface UnattributedRatings {
  count:        number
  avg:          number
  distribution: number[]
  recent:       EmployeeRatingEntry[]
}

export interface EmployeesRatingsResponse {
  employees:    EmployeeRatingStats[]
  unattributed: UnattributedRatings
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

export interface ConversationStats {
  total: number
  today: number
  this_week: number
  bot_handled: number
  admin_takeover: number
  avg_messages: number
  daily_counts: { date: string; count: number }[]
  hourly_distribution: number[]
}

export interface MessageStats {
  total: number
  user: number
  bot: number
  admin: number
}

export interface RatingStats {
  count: number
  avg: number
  distribution: number[]
}

export interface ChannelStats {
  conversations: ConversationStats
  messages:      MessageStats
  ratings:       RatingStats
}

export interface Analytics {
  conversations:   ConversationStats
  messages:        MessageStats
  ratings:         RatingStats
  abandoned_carts: { total: number; recovered: number; pending: number; recovery_rate: number }
  products:        { count: number; last_sync: string }
  /** New: same shape as the legacy top-level fields, split per channel. */
  by_channel?: {
    widget:   ChannelStats
    whatsapp: ChannelStats
    total:    ChannelStats
  }
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

export interface NotificationSettings {
  email_enabled:        boolean
  email_address:        string
  webhook_url:          string
  on_new_conversation:  boolean
  on_abandoned_cart:    boolean
  on_low_rating:        boolean
  quiet_hours_enabled:  boolean
  quiet_hours_start:    number
  quiet_hours_end:      number
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

// ── Support-access grants ──────────────────────────────────────────────

export interface SupportAccessGrant {
  id:          number
  store_id:    string
  granted_by:  string             // "owner" | "emp:<id>"
  granted_at:  string             // ISO timestamp
  expires_at:  string
  note:        string
  revoked_at:  string | null
  active?:     boolean            // present on history rows; absent on POST response
}

// ── Audit log ──────────────────────────────────────────────────────────
//
// One row per sensitive admin action. `actor` is a stable string id
// ("super" / "store:<id>" / "emp:<id>@<store>"). `details` is a
// per-action JSON blob — never contains raw secrets.

export interface AuditRow {
  id:            number
  actor:         string
  target_store:  string
  action:        string
  details:       Record<string, unknown>
  ip:            string
  user_agent:    string
  created_at:    string
}

// ── Platform Operations snapshot (super admin) ─────────────────────────
//
// Read-only operational metrics for the platform owner. NEVER contains
// raw secrets — token_status is a coarse bucket, provider is a label.

export interface PlatformOpsStoreRow {
  store_id:        string
  store_name:      string
  connected_at:    string
  last_activity:   string
  bot_enabled:     boolean
  channels:        { widget: boolean; whatsapp: boolean }
  token_status:    'valid' | 'expiring' | 'expired' | 'unknown'
  provider:        string  // 'groq' | 'anthropic' | 'openai' | '—'
  products_count:  number
  tokens_today:    number
  budget:          number
  percent_used:    number | null
}

export interface PlatformOpsSnapshot {
  totals: {
    stores_registered:    number
    stores_active_today:  number
    messages_today:       number
    tokens_today:         number
    llm_requests_today:   number
  }
  queues: {
    inbox:  Record<string, number>   // pending/processing/done/failed/dead
    outbox: Record<string, number>
  }
  errors: {
    webhook_errors_24h:       number
    webhook_sig_failures_24h: number
    login_failures_24h:       number
  }
  near_budget:       Array<{ store_id: string; store_name: string; tokens_today: number; budget: number; percent_used: number }>
  top_error_stores:  Array<{ store_id: string; errors: number }>
  outbox_dead_top:   Array<{ store_id: string; dead: number }>
  stores:            PlatformOpsStoreRow[]
}

// ── LLM usage / daily budget ───────────────────────────────────────────
//
// Shape mirrors /admin/{store}/llm-usage. `today.remaining` is null when
// the breaker is disabled (budget=0); UI should show "غير محدد" in that
// case rather than 0%.
export interface LlmUsageToday {
  tokens_in:    number
  tokens_out:   number
  tokens_total: number
  requests:     number
  budget:       number
  remaining:    number | null
  percent_used: number | null
  exhausted:    boolean
}

export interface LlmUsageHistoryRow {
  date:         string  // ISO date (YYYY-MM-DD)
  tokens_in:    number
  tokens_out:   number
  tokens_total: number
  requests:     number
}

export interface LlmUsageResponse {
  store_id: string
  today:    LlmUsageToday
  budget: {
    value:           number
    source:          'store_override' | 'env_default'
    breaker_active:  boolean
  }
  history: LlmUsageHistoryRow[]
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


// ── Realtime stream helper ──────────────────────────────────────────────
//
// Opens an authenticated SSE connection to /admin/{storeId}/stream and
// dispatches events to user-supplied handlers. Handles ticket exchange,
// auto-reconnect with backoff, and cleanup. Returns a function the caller
// invokes in their useEffect cleanup to tear down the connection.
//
// Why a wrapper: EventSource can't send Authorization headers. We POST
// (with bearer) to exchange for a single-use ticket and pass it via URL.
// Tickets expire in 5 minutes — we re-fetch on every (re)connect so a
// long-running tab survives token rotation cleanly.

export interface AdminStreamHandlers {
  /** New chat message landed (any role: user / assistant / admin). */
  onMessage?:        (data: StreamMessageEvent) => void
  /** First message in a brand-new session. */
  onNewConversation?: (data: { session_id: string; customer_name: string; first_message: string }) => void
  /** Customer submitted a CSAT rating. */
  onRating?:         (data: { session_id: string; rating: number }) => void
  /** Bot was toggled for a session (admin took over / handed back). */
  onBotToggle?:      (data: { session_id: string; bot_enabled: boolean }) => void
  /** Connection went down. Called once per disconnect, NOT on every retry. */
  onDisconnect?:     () => void
  /** Connection (re)established. */
  onConnect?:        () => void
}

export interface StreamMessageEvent {
  session_id: string
  store_id:   string
  role:       'user' | 'assistant' | 'admin' | string
  ts:         string
  preview:    string
}

const STREAM_BACKOFF_MAX_MS = 30_000

export function openAdminStream(
  storeId: string,
  handlers: AdminStreamHandlers,
  options: { reason?: string } = {},
): () => void {
  let es: EventSource | null = null
  let backoff = 1_000
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let closed = false

  async function connect() {
    if (closed) return
    let ticket: string
    try {
      // `reason` is only needed when a super admin opens a stream for a
      // store they don't own. Owner/employee calls leave it undefined
      // and pay no per-request cost.
      const r = await api.streamTicket(storeId, options.reason) as { ticket: string }
      ticket = r.ticket
    } catch {
      // Bearer expired, store_id mismatch, OR (super admin + missing
      // reason). Schedule a retry — the page's first explicit fetch will
      // surface the actual error (reason_required) and prompt the user;
      // a subsequent re-open call from the page can pass the reason in.
      scheduleReconnect()
      return
    }
    if (closed) return

    const url = `/admin/${encodeURIComponent(storeId)}/stream?ticket=${encodeURIComponent(ticket)}`
    es = new EventSource(url)

    es.addEventListener('connected', () => {
      backoff = 1_000
      handlers.onConnect?.()
    })

    es.addEventListener('new_message', (e: MessageEvent) => {
      try { handlers.onMessage?.(JSON.parse(e.data)) } catch {/* malformed — ignore */}
    })
    es.addEventListener('new_conversation', (e: MessageEvent) => {
      try { handlers.onNewConversation?.(JSON.parse(e.data)) } catch {/**/}
    })
    es.addEventListener('rating', (e: MessageEvent) => {
      try { handlers.onRating?.(JSON.parse(e.data)) } catch {/**/}
    })
    es.addEventListener('bot_toggle', (e: MessageEvent) => {
      try { handlers.onBotToggle?.(JSON.parse(e.data)) } catch {/**/}
    })
    es.addEventListener('shutdown', () => {
      // Server is restarting — close cleanly and let backoff reconnect.
      try { es?.close() } catch {/**/}
      scheduleReconnect()
    })

    es.onerror = () => {
      // EventSource auto-retries on transient errors. We trigger our own
      // reconnect only when the readyState shows the connection is
      // permanently CLOSED — otherwise we'd double-reconnect.
      if (es && es.readyState === 2 /* CLOSED */) {
        handlers.onDisconnect?.()
        scheduleReconnect()
      }
    }
  }

  function scheduleReconnect() {
    if (closed || reconnectTimer) return
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      backoff = Math.min(backoff * 2, STREAM_BACKOFF_MAX_MS)
      connect()
    }, backoff)
  }

  // Kick off the first connection asynchronously so the caller's render
  // pass isn't blocked by the ticket fetch.
  void connect()

  // Cleanup returned to the caller.
  return () => {
    closed = true
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (es) {
      try { es.close() } catch {/**/}
      es = null
    }
  }
}
