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

export function buildEnrollmentCurl(apiBaseUrl: string, token: string): string {
  const base = apiBaseUrl.replace(/\/$/, '')
  return `curl -fsSL "${base}/gateway-agent.sh?token=${encodeURIComponent(token)}" | CONTROL_PLANE_URL="${base}" ENROLL_TOKEN="${token}" bash`
}

export function buildWorkerEnrollmentCurl(
  apiBaseUrl: string,
  token: string,
): string {
  const base = apiBaseUrl.replace(/\/$/, '')
  return `curl -fsSL "${base}/worker-agent.sh?token=${encodeURIComponent(token)}" | CONTROL_PLANE_URL="${base}" ENROLL_TOKEN="${token}" bash`
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
