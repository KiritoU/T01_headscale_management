import { CheckCircle2, Cloud, Download, Loader2, Save, Settings, Shield } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { LoadingState } from '../../components/ui/PageState'
import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import type { PlatformConsoleSettings } from '../../types'

export function ConsoleSettingsPage() {
  const [settings, setSettings] = useState<PlatformConsoleSettings | null>(null)
  const [acmeEmail, setAcmeEmail] = useState('')
  const [cfToken, setCfToken] = useState('')
  const [downloadHost, setDownloadHost] = useState('')
  const [downloadTargetIp, setDownloadTargetIp] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [verifying, setVerifying] = useState(false)
  const [syncingDns, setSyncingDns] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getPlatformConsoleSettings()
      setSettings(data)
      setAcmeEmail(data.acme_email ?? '')
      setCfToken('')
      setDownloadHost(data.download_host ?? '')
      setDownloadTargetIp(data.download_target_ip ?? '')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load console settings')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    setMessage(null)
    try {
      const body: {
        acme_email?: string
        cf_dns_api_token?: string
        download_host?: string
        download_target_ip?: string | null
      } = {
        acme_email: acmeEmail.trim(),
        download_host: downloadHost.trim(),
        download_target_ip: downloadTargetIp.trim() || null,
      }
      if (cfToken.trim()) {
        body.cf_dns_api_token = cfToken.trim()
      }
      const updated = await api.updatePlatformConsoleSettings(body)
      setSettings(updated)
      setCfToken('')
      setMessage('Console settings saved.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save console settings')
    } finally {
      setSaving(false)
    }
  }

  const handleVerifyToken = async () => {
    setVerifying(true)
    setError(null)
    setMessage(null)
    try {
      const result = await api.verifyPlatformCloudflareToken()
      if (result.valid) {
        setMessage(result.message || 'Cloudflare token is valid.')
        await load()
      } else {
        setError(result.message || 'Cloudflare token verification failed.')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Token verification failed')
    } finally {
      setVerifying(false)
    }
  }

  const handleSyncDownloadDns = async () => {
    setSyncingDns(true)
    setError(null)
    setMessage(null)
    const host = downloadHost.trim()
    const ip = downloadTargetIp.trim()
    if (!host) {
      setError('Enter a download subdomain / host before creating the A record.')
      setSyncingDns(false)
      return
    }
    if (!ip) {
      setError('Enter a download target IP before creating the A record.')
      setSyncingDns(false)
      return
    }
    try {
      const body: {
        acme_email?: string
        cf_dns_api_token?: string
        download_host?: string
        download_target_ip?: string | null
      } = {
        acme_email: acmeEmail.trim(),
        download_host: host,
        download_target_ip: ip,
      }
      if (cfToken.trim()) {
        body.cf_dns_api_token = cfToken.trim()
      }
      const updated = await api.updatePlatformConsoleSettings(body)
      setSettings(updated)
      setCfToken('')
      const result = await api.syncPlatformDownloadDns()
      setMessage(`Download DNS synced for ${result.fqdn} -> ${result.target_ip}.`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to sync download DNS')
    } finally {
      setSyncingDns(false)
    }
  }

  if (loading) {
    return <LoadingState message="Loading console settings…" />
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center gap-3">
        <Settings className="h-6 w-6 text-primary" aria-hidden />
        <div>
          <h2 className="text-lg font-semibold text-white">Console settings</h2>
          <p className="text-sm text-ink-mute-2">
            Cloudflare DNS automation, TLS edge credentials, and centralized script download host
          </p>
        </div>
      </div>

      {error ? (
        <p role="alert" className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </p>
      ) : null}
      {message ? (
        <p role="status" className="rounded-md border border-primary/30 bg-primary/10 px-4 py-3 text-sm text-primary">
          {message}
        </p>
      ) : null}

      <section className="rounded-md border border-hairline bg-canvas-night-soft p-4">
        <div className="mb-3 flex items-center gap-2">
          <Shield className="h-4 w-4 text-primary" aria-hidden />
          <h3 className="text-sm font-semibold text-white">Cloudflare &amp; TLS</h3>
        </div>
        <p className="mb-4 text-xs text-ink-mute-2">
          One platform token is used for Traefik ACME DNS-01 and automatic A-record management.
        </p>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
            ACME email (Let&apos;s Encrypt)
            <input
              type="email"
              value={acmeEmail}
              onChange={(event) => setAcmeEmail(event.target.value)}
              placeholder="admin@example.com"
              className="rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
            Cloudflare DNS API token
            <input
              type="password"
              value={cfToken}
              onChange={(event) => setCfToken(event.target.value)}
              placeholder={
                settings?.cf_dns_api_token_configured
                  ? '••••••••  (leave blank to keep current)'
                  : 'cfat_…'
              }
              autoComplete="off"
              className="rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none"
            />
          </label>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button type="button" disabled={saving} onClick={() => void handleSave()}>
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Save className="h-4 w-4" aria-hidden />
            )}
            Save settings
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={verifying || !settings?.cf_dns_api_token_configured}
            onClick={() => void handleVerifyToken()}
          >
            {verifying ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Cloud className="h-4 w-4" aria-hidden />
            )}
            Verify token
          </Button>
          {settings?.cf_dns_api_token_configured ? (
            <span className="inline-flex items-center gap-1 text-xs text-primary">
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
              Token configured
              {settings.cf_dns_api_token_source === 'environment' ? ' · from .env' : ''}
              {settings.cf_token_verified_at
                ? ` · verified ${formatDateTime(settings.cf_token_verified_at)}`
                : ''}
            </span>
          ) : (
            <span className="text-xs text-amber-200">Cloudflare token not set</span>
          )}
        </div>
      </section>

      <section className="rounded-md border border-hairline bg-canvas-night-soft p-4">
        <div className="mb-3 flex items-center gap-2">
          <Download className="h-4 w-4 text-primary" aria-hidden />
          <h3 className="text-sm font-semibold text-white">Download host</h3>
        </div>
        <p className="mb-4 text-xs text-ink-mute-2">
          Client connection scripts are served centrally from this host, for example{' '}
          <code className="text-white">https://download.ovncr.vn/team-1/linux.sh</code>.
          Set <code className="text-white">DOWNLOAD_HOST</code> in <code className="text-white">.env</code> to match.
        </p>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
            Download subdomain / host
            <input
              type="text"
              value={downloadHost}
              onChange={(event) => setDownloadHost(event.target.value)}
              placeholder="download.ovncr.vn"
              className="rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
            Download target IP (console / Traefik)
            <input
              type="text"
              value={downloadTargetIp}
              onChange={(event) => setDownloadTargetIp(event.target.value)}
              placeholder="203.0.113.10"
              className="rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none"
            />
          </label>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="secondary"
            disabled={syncingDns}
            onClick={() => void handleSyncDownloadDns()}
          >
            {syncingDns ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Cloud className="h-4 w-4" aria-hidden />
            )}
            Create / update A record
          </Button>
          {settings?.download_dns_synced ? (
            <span className="inline-flex items-center gap-1 text-xs text-primary">
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
              DNS record synced
              {settings.download_dns_record_id
                ? ` (${settings.download_dns_record_id})`
                : ''}
            </span>
          ) : (
            <span className="text-xs text-amber-200">Download A record not synced yet</span>
          )}
        </div>
      </section>
    </div>
  )
}
