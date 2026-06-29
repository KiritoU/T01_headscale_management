export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return '—'
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export function formatHostUrl(
  host: string,
  desiredConfig?: Record<string, unknown>,
): string {
  if (host.startsWith('http://') || host.startsWith('https://')) {
    return host
  }
  const production = desiredConfig?.production === true
  const scheme = production ? 'https' : 'http'
  return `${scheme}://${host}`
}

function resolveTenantDownloadHost(
  desiredConfig?: Record<string, unknown>,
  platformDownloadHost?: string,
): string {
  if (platformDownloadHost?.trim()) {
    return platformDownloadHost.trim()
  }
  const configured = desiredConfig?.download_host
  if (typeof configured === 'string' && configured.trim()) {
    return configured.trim()
  }
  const baseDomain = desiredConfig?.base_domain
  if (typeof baseDomain === 'string' && baseDomain.trim()) {
    return `download.${baseDomain.trim()}`
  }
  return 'download.example.com'
}

export function buildTenantScriptUrl(
  slug: string,
  scriptName: string,
  desiredConfig?: Record<string, unknown>,
  platformDownloadHost?: string,
): string {
  const downloadHost = resolveTenantDownloadHost(
    desiredConfig,
    platformDownloadHost,
  )
  return `${formatHostUrl(downloadHost, desiredConfig)}/${slug}/${scriptName}`
}

export function buildTenantConnectCommand(
  slug: string,
  scriptName: string,
  desiredConfig?: Record<string, unknown>,
  platformDownloadHost?: string,
): string {
  const url = buildTenantScriptUrl(
    slug,
    scriptName,
    desiredConfig,
    platformDownloadHost,
  )
  if (scriptName.endsWith('.ps1')) {
    return `irm "${url}" | iex`
  }
  return `curl -fsSL "${url}" | sh`
}

export function buildEnrollmentCurl(apiBaseUrl: string, token: string): string {
  const base = apiBaseUrl.replace(/\/$/, '')
  return `curl -fsSL "${base}/gateway-agent.sh?token=${encodeURIComponent(token)}" | bash`
}

export function buildWorkerEnrollmentCurl(
  apiBaseUrl: string,
  token: string,
): string {
  const base = apiBaseUrl.replace(/\/$/, '')
  return `curl -fsSL "${base}/worker-agent.sh?token=${encodeURIComponent(token)}" | bash`
}

export function formatExpiryCountdown(
  expiresAt: string | null | undefined,
): string {
  if (!expiresAt) {
    return 'No expiry'
  }
  const remainingMs = new Date(expiresAt).getTime() - Date.now()
  if (remainingMs <= 0) {
    return 'Expired'
  }
  const totalSeconds = Math.floor(remainingMs / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes > 0) {
    return `Expires in ${minutes}m ${seconds}s`
  }
  return `Expires in ${seconds}s`
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '—'
  }
  return `${value.toFixed(1)}%`
}

export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '—'
  }
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = value
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }
  const digits = unitIndex === 0 ? 0 : size >= 100 ? 0 : size >= 10 ? 1 : 2
  return `${size.toFixed(digits)} ${units[unitIndex]}`
}

export function formatBytesPerSec(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '—'
  }
  return `${formatBytes(value)}/s`
}

export function formatUptime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return '—'
  }
  const total = Math.floor(seconds)
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  if (days > 0) {
    return `${days}d ${hours}h`
  }
  if (hours > 0) {
    return `${hours}h ${minutes}m`
  }
  return `${minutes}m`
}
