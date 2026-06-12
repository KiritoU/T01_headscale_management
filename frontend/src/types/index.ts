export type BootstrapStatus =
  | 'pending'
  | 'provisioning'
  | 'bootstrapped'
  | 'failed'

export type RuntimeStatus =
  | 'pending'
  | 'provisioning'
  | 'running'
  | 'stopped'
  | 'failed'

export type WorkerStatus = 'pending' | 'online' | 'offline' | 'disabled'

export interface Tenant {
  id: string
  slug: string
  headscale_host: string
  headplane_host: string
  db_name: string
  worker: string | null
  worker_name: string | null
  bootstrap_status: BootstrapStatus
  desired_config: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface TenantHealth {
  id: string
  probed_at: string
  latency_ms: number
  healthy: boolean
  error_message: string
}

export interface TenantBootstrapInfo {
  command_id: string | null
  acked_at: string | null
  admin_user_id: string | null
  api_key: string | null
  auth_key_gateway: string | null
  auth_key_workspace: string | null
  output_ref: string | null
}

export interface TenantDetail extends Tenant {
  runtime_status: RuntimeStatus
  bootstrap_output_ref: string
  health_checks: TenantHealth[]
  bootstrap_info: TenantBootstrapInfo | null
}

export interface Worker {
  id: string
  name: string
  hostname: string
  status: WorkerStatus
  credential_ref: string
  docker_reachable: boolean
  installed_modules?: string[]
  last_heartbeat_at: string | null
  created_at: string
  updated_at: string
}

export interface WorkerEnrollmentToken {
  token: string
  worker_id: string
  expires_at: string | null
  name: string
}

export interface TenantActionResult {
  command_id?: string
  message?: string
}

export interface WorkerTenant {
  id: string
  slug: string
  headscale_host: string
  headplane_host: string
  db_name: string
  bootstrap_status: BootstrapStatus
  runtime_status: RuntimeStatus
  bootstrap_output_ref: string
  desired_config: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface WorkerTenantDetail extends WorkerTenant {
  health_checks: TenantHealth[]
  bootstrap_info: TenantBootstrapInfo | null
}

export interface WorkerTenantSummary {
  total: number
  bootstrap_status: Record<string, number>
  runtime_status: Record<string, number>
}

export interface WorkerTenantBulkCreateParams {
  suffix: string
  start_number: number
  count: number
  base_domain: string
  production?: boolean
}

export interface WorkerTenantActionResult {
  command_id?: string | null
  command?: string | null
  state?: string | null
  skipped?: boolean
  runtime_status?: RuntimeStatus
  bootstrap_output_ref?: string
  bootstrap_status?: BootstrapStatus
}

export interface WorkerTenantBulkProvisionResult {
  command_id?: string | null
  command?: string | null
  state?: string | null
  skipped?: boolean
}

export type GatewayStatus =
  | 'pending'
  | 'enrolled'
  | 'online'
  | 'offline'
  | 'disabled'

export interface Gateway {
  id: string
  tenant_id: string
  tenant_slug: string
  hostname: string
  status: GatewayStatus
  agent_id: string | null
  custom_tags: string[]
  tailscale_node_id: string
  last_heartbeat_at: string | null
  installed_modules: string[]
  created_at: string
  updated_at: string
  last_discover_scan?: GatewayCommandDetail | null
  last_target_scan?: GatewayCommandDetail | null
}

export interface GatewayCommand {
  id: string
  command: string
  payload: Record<string, unknown>
  state: string
  created_at: string
}

export interface GatewayCommandResult {
  exit_code?: number
  duration_ms?: number
  logs?: string
  subnets?: ScanSubnet[]
  nmap_available?: boolean
}

export interface GatewayCommandDetail extends GatewayCommand {
  result?: GatewayCommandResult
}

export interface EnrollmentTokenResult {
  token_id: string
  token: string
  prefix: string
  max_uses: number
  expires_at: string | null
}

export interface ScanHost {
  ip: string
  hostname?: string
  mac?: string
  status: 'up' | 'down' | 'unknown'
}

export interface ScanSummary {
  subnet_count: number
  total_hosts: number
  local_networks: number
  target_networks: number
}

export interface ScanSubnet {
  cidr: string
  interface: string
  source: string
  live_hosts: number | null
  hosts?: ScanHost[]
  scan_mode?: 'discover' | 'target'
  is_local?: boolean
}

export interface GatewayRoute {
  cidr: string
  approved: boolean
  enabled: boolean
}

export interface TailscaleTenantOption {
  id: string
  slug: string
  headscale_host: string
  bootstrap_status: BootstrapStatus
  credentials_ready: boolean
}

export interface TenantTailscalePreview {
  tenant_id: string
  slug: string
  login_server: string
  auth_key_available: boolean
  auth_key_hint: string | null
}

export interface TailscaleLastScan {
  command_id: string
  scan_mode: 'discover' | 'target'
  acked_at: string
  subnets: ScanSubnet[]
  summary: ScanSummary
}

export interface TailscaleUpOptionDefaults {
  force_reauth: boolean
  accept_dns: boolean
  reset: boolean
}

export interface TailscaleConnectContext {
  gateway_tenant_id: string
  tenants: TailscaleTenantOption[]
  default_tenant_id: string
  tenant_preview: TenantTailscalePreview
  last_scan: TailscaleLastScan | null
  option_defaults: TailscaleUpOptionDefaults
}

export interface TailscaleUpOptions {
  force_reauth: boolean
  accept_dns: boolean
  reset: boolean
}
