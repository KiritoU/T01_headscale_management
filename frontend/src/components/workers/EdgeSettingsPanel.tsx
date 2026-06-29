import { Loader2, Save, Shield } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Button } from '../ui/Button'
import { api } from '../../lib/api'
import type { PlatformEdgeSettings } from '../../types'

export function EdgeSettingsPanel() {
  const [settings, setSettings] = useState<PlatformEdgeSettings | null>(null)
  const [acmeEmail, setAcmeEmail] = useState('')
  const [cfToken, setCfToken] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getPlatformEdgeSettings()
      setSettings(data)
      setAcmeEmail(data.acme_email ?? '')
      setCfToken('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load edge settings')
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
      const body: { acme_email?: string; cf_dns_api_token?: string } = {
        acme_email: acmeEmail.trim(),
      }
      if (cfToken.trim()) {
        body.cf_dns_api_token = cfToken.trim()
      }
      const updated = await api.updatePlatformEdgeSettings(body)
      setSettings(updated)
      setCfToken('')
      setMessage('Edge settings saved.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save edge settings')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-hairline bg-canvas-night-soft px-4 py-3 text-sm text-ink-mute-2">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        Loading edge settings…
      </div>
    )
  }

  return (
    <section className="rounded-md border border-hairline bg-canvas-night-soft p-4">
      <div className="mb-3 flex items-center gap-2">
        <Shield className="h-4 w-4 text-primary" aria-hidden />
        <h2 className="text-sm font-semibold text-white">Edge &amp; TLS settings</h2>
      </div>
      <p className="mb-4 text-xs text-ink-mute-2">
        Used for production tenant stacks. Workers with shared edge use the console
        Traefik for HTTPS; remote workers use these credentials for their own Traefik.
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
          Save edge settings
        </Button>
        {settings?.cf_dns_api_token_configured ? (
          <span className="text-xs text-primary">Cloudflare token configured</span>
        ) : (
          <span className="text-xs text-amber-200">Cloudflare token not set</span>
        )}
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-red-200">
          {error}
        </p>
      ) : null}
      {message ? (
        <p role="status" className="mt-3 text-sm text-primary">
          {message}
        </p>
      ) : null}
    </section>
  )
}
