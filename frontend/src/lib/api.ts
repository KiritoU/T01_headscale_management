import type {
  AuthMeResponse,
  AuthUser,
  EnrollmentTokenResult,
  Gateway,
  GatewayCommand,
  GatewayCommandDetail,
  GatewayRoute,
  ResourceGrant,
  Role,
  TailscaleConnectContext,
  DiscoveredHost,
  EnsureMonitoringModulesResult,
  GatewayMonitoringListParams,
  GatewayMonitoringScanResult,
  GatewayMonitoringVulnRescanResult,
  GatewayMonitorPolicy,
  GatewayMonitorPolicyPatch,
  MonitorAlert,
  PaginatedResult,
  PaginationMeta,
  Tenant,
  VulnFinding,
  TenantActionResult,
  TenantDetail,
  Worker,
  WorkerEnrollmentToken,
  WorkerTenant,
  WorkerTenantDetail,
  WorkerTenantActionResult,
  WorkerTenantBulkCreateParams,
  WorkerTenantBulkProvisionResult,
  WorkerTenantSummary,
} from '../types'

/** Same-origin by default (Docker nginx). Set VITE_API_URL only for split dev hosts. */
const API_URL = import.meta.env.VITE_API_URL ?? ''

export function getApiBaseUrl(): string {
  if (API_URL) {
    return API_URL.replace(/\/$/, '')
  }
  if (typeof window !== 'undefined') {
    return window.location.origin
  }
  return 'http://localhost:8000'
}

export interface ApiEnvelope<T> {
  success: boolean
  data: T
  error: string | null
  meta: Record<string, unknown>
}

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

let cachedCsrfToken: string | null = null

function readCsrfCookie(): string | null {
  if (typeof document === 'undefined') {
    return null
  }
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

export function getCsrfToken(): string | null {
  return cachedCsrfToken ?? readCsrfCookie()
}

export async function bootstrapCsrf(): Promise<string> {
  const data = await request<{ csrf_token: string }>('/api/auth/csrf/', {
    skipAuthRedirect: true,
  })
  cachedCsrfToken = data.csrf_token
  return data.csrf_token
}

const AUTH_EXEMPT_PATHS = [
  '/api/auth/login/',
  '/api/auth/logout/',
  '/api/auth/csrf/',
  '/api/auth/me/',
]

interface RequestOptions extends RequestInit {
  skipAuthRedirect?: boolean
}

function isEnvelope<T>(body: unknown): body is ApiEnvelope<T> {
  return (
    typeof body === 'object' &&
    body !== null &&
    'success' in body &&
    'data' in body &&
    'error' in body
  )
}

async function parseJson(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) {
    return null
  }
  try {
    return JSON.parse(text) as unknown
  } catch {
    throw new ApiError('Invalid JSON response from API', response.status)
  }
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = `${API_URL}${path}`
  const headers = new Headers(options.headers)
  const method = (options.method ?? 'GET').toUpperCase()
  const isMutating = !['GET', 'HEAD', 'OPTIONS'].includes(method)

  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  if (isMutating) {
    const csrfToken = getCsrfToken()
    if (csrfToken) {
      headers.set('X-CSRFToken', csrfToken)
    }
  }

  const { skipAuthRedirect, ...fetchOptions } = options
  const response = await fetch(url, {
    ...fetchOptions,
    headers,
    credentials: 'include',
  })
  const body = await parseJson(response)

  if (
    response.status === 401 &&
    !skipAuthRedirect &&
    !AUTH_EXEMPT_PATHS.some((exemptPath) => path.startsWith(exemptPath)) &&
    typeof window !== 'undefined' &&
    !window.location.pathname.startsWith('/login')
  ) {
    window.location.assign('/login')
  }

  if (isEnvelope<T>(body)) {
    if (!body.success) {
      throw new ApiError(body.error ?? 'Request failed', response.status)
    }
    return body.data
  }

  if (!response.ok) {
    const message =
      typeof body === 'object' &&
      body !== null &&
      'error' in body &&
      typeof (body as ApiEnvelope<unknown>).error === 'string'
        ? (body as ApiEnvelope<unknown>).error!
        : `HTTP ${response.status}`
    throw new ApiError(message, response.status)
  }

  return body as T
}

export interface ListTenantsParams {
  bootstrap_status?: string
  worker?: string
  slug?: string
}

function buildQuery(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value) {
      search.set(key, value)
    }
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

function buildMonitoringQuery(params?: GatewayMonitoringListParams): string {
  if (!params) {
    return ''
  }
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value))
    }
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

async function requestPaginated<T>(
  path: string,
  params?: GatewayMonitoringListParams,
): Promise<PaginatedResult<T>> {
  const url = `${API_URL}${path}${buildMonitoringQuery(params)}`
  const headers = new Headers()
  const response = await fetch(url, {
    headers,
    credentials: 'include',
  })
  const body = await parseJson(response)

  if (
    response.status === 401 &&
    !AUTH_EXEMPT_PATHS.some((exemptPath) => path.startsWith(exemptPath)) &&
    typeof window !== 'undefined' &&
    !window.location.pathname.startsWith('/login')
  ) {
    window.location.assign('/login')
  }

  if (isEnvelope<T[]>(body)) {
    if (!body.success) {
      throw new ApiError(body.error ?? 'Request failed', response.status)
    }
    const meta = body.meta as Partial<PaginationMeta>
    return {
      items: body.data,
      meta: {
        total: Number(meta.total ?? body.data.length),
        page: Number(meta.page ?? 1),
        limit: Number(meta.limit ?? body.data.length),
        pages: Number(meta.pages ?? 1),
      },
    }
  }

  if (!response.ok) {
    throw new ApiError(`HTTP ${response.status}`, response.status)
  }

  const items = body as T[]
  return {
    items,
    meta: {
      total: items.length,
      page: 1,
      limit: items.length,
      pages: 1,
    },
  }
}

export const api = {
  getMe: () =>
    request<AuthMeResponse>('/api/auth/me/', { skipAuthRedirect: true }),

  login: (username: string, password: string) =>
    request<AuthUser>('/api/auth/login/', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
      skipAuthRedirect: true,
    }),

  logout: () =>
    request<null>('/api/auth/logout/', {
      method: 'POST',
      skipAuthRedirect: true,
    }),

  listAdminUsers: () => request<AuthUser[]>('/api/admin/users/'),

  createAdminUser: (body: {
    username: string
    password: string
    role: Role
    email?: string
  }) =>
    request<AuthUser>('/api/admin/users/', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  deleteAdminUser: (userId: string) =>
    request<null>(`/api/admin/users/${userId}/`, {
      method: 'DELETE',
    }),

  listUserGrants: (userId: string) =>
    request<ResourceGrant[]>(`/api/admin/users/${userId}/grants/`),

  createUserGrant: (
    userId: string,
    body: {
      scope_type: string
      scope_id: string
      access_level: string
    },
  ) =>
    request<ResourceGrant>(`/api/admin/users/${userId}/grants/`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  deleteGrant: (grantId: string) =>
    request<null>(`/api/admin/grants/${grantId}/`, {
      method: 'DELETE',
    }),

  listTenants: (params: ListTenantsParams = {}) =>
    request<Tenant[]>(
      `/api/tenants/${buildQuery({
        bootstrap_status: params.bootstrap_status,
        worker: params.worker,
        slug: params.slug,
      })}`,
    ),

  getTenant: (id: string) => request<TenantDetail>(`/api/tenants/${id}/`),

  verifyTenant: (id: string) =>
    request<TenantActionResult>(`/api/tenants/${id}/verify/`, {
      method: 'POST',
    }),

  bootstrapTenant: (id: string) =>
    request<TenantActionResult>(`/api/tenants/${id}/bootstrap/`, {
      method: 'POST',
    }),

  listWorkers: () => request<Worker[]>('/api/workers/'),

  getWorker: (id: string) => request<Worker>(`/api/workers/${id}/`),

  createWorkerEnrollmentToken: (
    name: string,
    expires_in_minutes?: number,
  ) =>
    request<WorkerEnrollmentToken>('/api/workers/enrollment-tokens/', {
      method: 'POST',
      body: JSON.stringify({
        name,
        ...(expires_in_minutes !== undefined ? { expires_in_minutes } : {}),
      }),
    }),

  disconnectWorker: (id: string) =>
    request<Worker>(`/api/workers/${id}/disconnect/`, {
      method: 'POST',
    }),

  deleteWorker: (id: string) =>
    request<null>(`/api/workers/${id}/`, {
      method: 'DELETE',
    }),

  installWorkerModule: (id: string, module: 'docker') =>
    request<GatewayCommand>(`/api/workers/${id}/commands/`, {
      method: 'POST',
      body: JSON.stringify({
        command: 'install_module',
        payload: { module },
      }),
    }),

  getWorkerTenantSummary: (workerId: string) =>
    request<WorkerTenantSummary>(`/api/workers/${workerId}/tenants/summary/`),

  listWorkerTenants: (workerId: string) =>
    request<WorkerTenant[]>(`/api/workers/${workerId}/tenants/`),

  getWorkerTenant: (workerId: string, tenantId: string) =>
    request<WorkerTenantDetail>(
      `/api/workers/${workerId}/tenants/${tenantId}/`,
    ),

  bulkCreateWorkerTenants: (
    workerId: string,
    body: WorkerTenantBulkCreateParams,
  ) =>
    request<WorkerTenant[]>(`/api/workers/${workerId}/tenants/bulk-create/`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  bulkProvisionWorkerTenants: (workerId: string) =>
    request<WorkerTenantBulkProvisionResult[]>(
      `/api/workers/${workerId}/tenants/bulk-provision/`,
      { method: 'POST' },
    ),

  provisionWorkerTenant: (workerId: string, tenantId: string) =>
    request<WorkerTenantActionResult>(
      `/api/workers/${workerId}/tenants/${tenantId}/provision/`,
      { method: 'POST' },
    ),

  startWorkerTenant: (workerId: string, tenantId: string) =>
    request<WorkerTenantActionResult>(
      `/api/workers/${workerId}/tenants/${tenantId}/start/`,
      { method: 'POST' },
    ),

  stopWorkerTenant: (workerId: string, tenantId: string) =>
    request<WorkerTenantActionResult>(
      `/api/workers/${workerId}/tenants/${tenantId}/stop/`,
      { method: 'POST' },
    ),

  verifyWorkerTenant: (workerId: string, tenantId: string) =>
    request<WorkerTenantActionResult>(
      `/api/workers/${workerId}/tenants/${tenantId}/verify/`,
      { method: 'POST' },
    ),

  bootstrapWorkerTenant: (workerId: string, tenantId: string) =>
    request<WorkerTenantActionResult>(
      `/api/workers/${workerId}/tenants/${tenantId}/bootstrap/`,
      { method: 'POST' },
    ),

  removeWorkerTenant: (workerId: string, tenantId: string) =>
    request<null>(`/api/workers/${workerId}/tenants/${tenantId}/`, {
      method: 'DELETE',
    }),

  listGateways: (params: { tenant_id?: string } = {}) =>
    request<Gateway[]>(
      `/api/gateways/${buildQuery({ tenant_id: params.tenant_id })}`,
    ),

  getGateway: (id: string) => request<Gateway>(`/api/gateways/${id}/`),

  deleteGateway: (id: string) =>
    request<null>(`/api/gateways/${id}/`, {
      method: 'DELETE',
    }),

  getGatewayCommand: (gatewayId: string, cmdId: string) =>
    request<GatewayCommandDetail>(
      `/api/gateways/${gatewayId}/commands/${cmdId}/`,
    ),

  patchGatewayTags: (id: string, custom_tags: string[]) =>
    request<Gateway>(`/api/gateways/${id}/tags/`, {
      method: 'PATCH',
      body: JSON.stringify({ custom_tags }),
    }),

  sendGatewayCommand: (
    id: string,
    body: { command: string; payload?: Record<string, unknown> },
  ) =>
    request<GatewayCommand>(`/api/gateways/${id}/commands/`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  createEnrollmentToken: (
    tenantId: string,
    body: { max_uses?: number } = {},
  ) =>
    request<EnrollmentTokenResult>(
      `/api/tenants/${tenantId}/gateways/enrollment-tokens/`,
      {
        method: 'POST',
        body: JSON.stringify(body),
      },
    ),

  getGatewayRoutes: async (gatewayId: string) => {
    const data = await request<{ routes: GatewayRoute[] }>(
      `/api/gateways/${gatewayId}/routes/`,
    )
    return data.routes ?? []
  },

  getTailscaleConnectContext: (gatewayId: string, tenantId?: string) =>
    request<TailscaleConnectContext>(
      `/api/gateways/${gatewayId}/tailscale-up/context/${buildQuery({
        tenant_id: tenantId,
      })}`,
    ),

  getGatewayMonitoring: (gatewayId: string) =>
    request<GatewayMonitorPolicy>(`/api/gateways/${gatewayId}/monitoring/`),

  patchGatewayMonitoring: (
    gatewayId: string,
    body: GatewayMonitorPolicyPatch,
  ) =>
    request<GatewayMonitorPolicy>(`/api/gateways/${gatewayId}/monitoring/`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  getGatewayMonitoringHosts: (
    gatewayId: string,
    params?: GatewayMonitoringListParams,
  ) =>
    requestPaginated<DiscoveredHost>(
      `/api/gateways/${gatewayId}/monitoring/hosts/`,
      params,
    ),

  getGatewayMonitoringAlerts: (
    gatewayId: string,
    params?: GatewayMonitoringListParams,
  ) =>
    requestPaginated<MonitorAlert>(
      `/api/gateways/${gatewayId}/monitoring/alerts/`,
      params,
    ),

  getGatewayMonitoringFindings: (
    gatewayId: string,
    params?: GatewayMonitoringListParams,
  ) =>
    requestPaginated<VulnFinding>(
      `/api/gateways/${gatewayId}/monitoring/findings/`,
      params,
    ),

  ensureGatewayMonitoringModules: (gatewayId: string) =>
    request<EnsureMonitoringModulesResult>(
      `/api/gateways/${gatewayId}/monitoring/modules/ensure/`,
      { method: 'POST' },
    ),

  triggerGatewayMonitoringScan: (gatewayId: string) =>
    request<GatewayMonitoringScanResult>(
      `/api/gateways/${gatewayId}/monitoring/scan/`,
      { method: 'POST' },
    ),

  triggerGatewayMonitoringVulnRescan: (
    gatewayId: string,
    body?: { ip?: string },
  ) =>
    request<GatewayMonitoringVulnRescanResult>(
      `/api/gateways/${gatewayId}/monitoring/vuln-rescan/`,
      { method: 'POST', body: JSON.stringify(body ?? {}) },
    ),
}
