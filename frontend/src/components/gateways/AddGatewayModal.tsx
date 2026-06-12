import { Copy, Loader2, Network, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Button } from '../ui/Button'
import { api, getApiBaseUrl } from '../../lib/api'
import { copyToClipboard } from '../../lib/clipboard'
import { buildEnrollmentCurl } from '../../lib/format'
import type { EnrollmentTokenResult, Tenant } from '../../types'

interface AddGatewayModalProps {
  open: boolean
  tenants: Tenant[]
  defaultTenantId?: string
  onClose: () => void
  /** Called after enrollment token is created so the parent can watch for the new gateway. */
  onEnrollmentTokenCreated?: (tenantId: string) => void
  watchingEnrollment?: boolean
}

export function AddGatewayModal({
  open,
  tenants,
  defaultTenantId = '',
  onClose,
  onEnrollmentTokenCreated,
  watchingEnrollment = false,
}: AddGatewayModalProps) {
  const [tenantId, setTenantId] = useState(defaultTenantId)
  const [maxUses, setMaxUses] = useState(1)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [enrollment, setEnrollment] = useState<EnrollmentTokenResult | null>(
    null,
  )
  const [copying, setCopying] = useState(false)
  const [copyMessage, setCopyMessage] = useState<string | null>(null)

  const resetForm = useCallback(() => {
    setTenantId(defaultTenantId)
    setMaxUses(1)
    setSubmitting(false)
    setError(null)
    setEnrollment(null)
    setCopying(false)
    setCopyMessage(null)
  }, [defaultTenantId])

  const handleClose = useCallback(() => {
    resetForm()
    onClose()
  }, [onClose, resetForm])

  useEffect(() => {
    if (open) {
      setTenantId(defaultTenantId || tenants[0]?.id || '')
    }
  }, [open, defaultTenantId, tenants])

  useEffect(() => {
    if (!open) {
      return
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        handleClose()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, handleClose])

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!tenantId) {
      setError('Select a tenant for this gateway.')
      return
    }

    setSubmitting(true)
    setError(null)
    try {
      const result = await api.createEnrollmentToken(tenantId, {
        max_uses: maxUses,
      })
      setEnrollment(result)
      onEnrollmentTokenCreated?.(tenantId)
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to create enrollment token',
      )
    } finally {
      setSubmitting(false)
    }
  }

  const handleCopy = async () => {
    if (!enrollment) {
      return
    }
    setCopying(true)
    setCopyMessage(null)
    try {
      const curl = buildEnrollmentCurl(getApiBaseUrl(), enrollment.token)
      await copyToClipboard(curl)
      setCopyMessage('Install command copied to clipboard.')
    } catch {
      setCopyMessage('Could not copy — select the command above and copy manually.')
    } finally {
      setCopying(false)
    }
  }

  if (!open) {
    return null
  }

  const selectedTenant = tenants.find((tenant) => tenant.id === tenantId)
  const curlCommand = enrollment
    ? buildEnrollmentCurl(getApiBaseUrl(), enrollment.token)
    : ''

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="presentation"
    >
      <button
        type="button"
        aria-label="Close modal"
        className="absolute inset-0 cursor-pointer bg-black/60"
        onClick={handleClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-gateway-title"
        className="relative z-10 w-full max-w-lg rounded-md border border-hairline bg-canvas-night-soft shadow-xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-hairline px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-sm bg-primary/15 text-primary">
              <Network className="h-4 w-4" aria-hidden />
            </span>
            <div>
              <h2
                id="add-gateway-title"
                className="text-base font-semibold text-white"
              >
                Enroll gateway
              </h2>
              <p className="text-xs text-ink-mute-2">
                Generate a curl command for a new subnet router agent
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="cursor-pointer rounded-sm p-1 text-ink-mute-2 transition-colors hover:bg-white/5 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            aria-label="Close"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>

        <div className="px-5 py-4">
          {enrollment ? (
            <div className="space-y-4">
              <div
                role="status"
                className="rounded-sm border border-primary/30 bg-primary/10 px-4 py-3 text-sm text-primary"
              >
                Enrollment token created for tenant{' '}
                <span className="font-medium">
                  {selectedTenant?.slug ?? tenantId}
                </span>
                . Run the command on the target Linux VM or server.
                {watchingEnrollment ? (
                  <span className="mt-2 flex items-center gap-2 text-primary/90">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                    Waiting for gateway to register…
                  </span>
                ) : (
                  <span className="mt-2 block text-primary/80">
                    The gateway list updates automatically after the agent enrolls.
                  </span>
                )}
              </div>

              <div className="space-y-2">
                <label className="text-xs font-medium uppercase tracking-wide text-ink-mute-2">
                  Install command
                </label>
                <pre className="overflow-x-auto rounded-sm border border-hairline bg-canvas-night p-3 font-mono text-xs leading-relaxed text-white">
                  {curlCommand}
                </pre>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button disabled={copying} onClick={() => void handleCopy()}>
                  {copying ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : (
                    <Copy className="h-4 w-4" aria-hidden />
                  )}
                  Copy install command
                </Button>
                <Button variant="secondary" onClick={handleClose}>
                  Done
                </Button>
              </div>

              {copyMessage ? (
                <p role="status" className="text-sm text-primary">
                  {copyMessage}
                </p>
              ) : null}
            </div>
          ) : (
            <form className="space-y-4" onSubmit={(event) => void handleSubmit(event)}>
              <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
                Tenant
                <select
                  value={tenantId}
                  onChange={(event) => setTenantId(event.target.value)}
                  disabled={submitting || tenants.length === 0}
                  className="cursor-pointer rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none disabled:opacity-50"
                  required
                >
                  <option value="" disabled>
                    Select tenant…
                  </option>
                  {tenants.map((tenant) => (
                    <option key={tenant.id} value={tenant.id}>
                      {tenant.slug}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
                Max uses
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={maxUses}
                  onChange={(event) =>
                    setMaxUses(Number.parseInt(event.target.value, 10) || 1)
                  }
                  disabled={submitting}
                  className="rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none disabled:opacity-50"
                />
              </label>

              {error ? (
                <p role="alert" className="text-sm text-red-200">
                  {error}
                </p>
              ) : null}

              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={submitting || tenants.length === 0}>
                  {submitting ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : null}
                  Generate enrollment command
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={submitting}
                  onClick={handleClose}
                >
                  Cancel
                </Button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
