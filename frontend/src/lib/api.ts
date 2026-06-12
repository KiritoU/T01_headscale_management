import type {
  EnrollmentTokenResult,
  Gateway,
  GatewayCommand,
  GatewayCommandDetail,
  GatewayRoute,
  TailscaleConnectContext,
  Tenant,
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

/** In dev, default to same-origin so Vite proxy works when accessing via server IP. */
const API_URL =
  import.meta.env.VITE_API_URL ??
  (import.meta.env.DEV ? '' : 'http://localhost:8000')

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

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_URL}${path}`
  const headers = new Headers(options.headers)

  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(url, { ...options, headers })
  const body = await parseJson(response)

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

export const api = {
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
}
