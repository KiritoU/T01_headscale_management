import { ArrowLeft, ExternalLink, Loader2, Play } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { TenantBootstrapPanel } from '../components/tenants/TenantBootstrapPanel'
import { TenantConnectPanel } from '../components/tenants/TenantConnectPanel'
import { TenantHealthPanel } from '../components/tenants/TenantHealthPanel'
import { Button } from '../components/ui/Button'
import { ErrorState, LoadingState } from '../components/ui/PageState'
import {
  BootstrapStatusBadge,
  RuntimeStatusBadge,
} from '../components/ui/StatusBadge'
import { usePeriodicTenantVerify } from '../hooks/usePeriodicTenantVerify'
import { api } from '../lib/api'
import { formatDateTime, formatHostUrl } from '../lib/format'
import { shouldShowBootstrapButton } from '../lib/tenantLifecycle'
import type { BootstrapStatus, RuntimeStatus, TenantDetail } from '../types'

export function TenantDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [tenant, setTenant] = useState<TenantDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [bootstrapping, setBootstrapping] = useState(false)

  const loadTenant = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!id) {
        return
      }
      if (!options?.silent) {
        setLoading(true)
        setError(null)
      }
      try {
        const data = await api.getTenant(id)
        setTenant(data)
      } catch (err) {
        if (!options?.silent) {
          setError(err instanceof Error ? err.message : 'Failed to load tenant')
        }
      } finally {
        if (!options?.silent) {
          setLoading(false)
        }
      }
    },
    [id],
  )

  useEffect(() => {
    void loadTenant()
  }, [loadTenant])

  const refreshTenant = useCallback(async () => {
    await loadTenant({ silent: true })
  }, [loadTenant])

  const verifyTenant = useCallback(async () => {
    if (!id) {
      return
    }
    await api.verifyTenant(id)
  }, [id])

  usePeriodicTenantVerify({
    enabled: Boolean(id && tenant && !loading && !error),
    verify: verifyTenant,
    refresh: refreshTenant,
  })

  const runBootstrap = async () => {
    if (!id) {
      return
    }
    setActionError(null)
    setActionMessage(null)
    setBootstrapping(true)
    try {
      const result = await api.bootstrapTenant(id)
      const message =
        result.message ??
        (result.command_id
          ? `Bootstrap command queued (${result.command_id})`
          : 'Bootstrap command dispatched')
      setActionMessage(message)
      await loadTenant({ silent: true })
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : 'Failed to bootstrap tenant',
      )
    } finally {
      setBootstrapping(false)
    }
  }

  if (!id) {
    return <ErrorState message="Tenant ID is missing." />
  }

  if (loading) {
    return <LoadingState message="Loading tenant…" />
  }

  if (error || !tenant) {
    return (
      <div className="space-y-4">
        <Link
          to="/tenants"
          className="inline-flex cursor-pointer items-center gap-2 text-sm text-ink-mute-2 hover:text-primary"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
          Back to tenants
        </Link>
        <ErrorState
          message={error ?? 'Tenant not found'}
          onRetry={() => void loadTenant()}
        />
      </div>
    )
  }

  const showBootstrap = shouldShowBootstrapButton(
    tenant.bootstrap_status as BootstrapStatus,
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <Link
            to="/tenants"
            className="inline-flex cursor-pointer items-center gap-2 text-sm text-ink-mute-2 hover:text-primary"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden />
            Back to tenants
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-lg font-semibold text-white">{tenant.slug}</h2>
            <BootstrapStatusBadge
              status={tenant.bootstrap_status as BootstrapStatus}
            />
            {tenant.runtime_status ? (
              <RuntimeStatusBadge
                status={tenant.runtime_status as RuntimeStatus}
              />
            ) : null}
          </div>
          <p className="font-mono text-xs text-ink-mute-2">{tenant.id}</p>
        </div>

        {showBootstrap ? (
          <div className="flex flex-wrap gap-2">
            <Button disabled={bootstrapping} onClick={() => void runBootstrap()}>
              {bootstrapping ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Play className="h-4 w-4" aria-hidden />
              )}
              Bootstrap
            </Button>
          </div>
        ) : null}
      </div>

      {actionMessage ? (
        <div
          role="status"
          className="rounded-sm border border-primary/30 bg-primary/10 px-4 py-3 text-sm text-primary"
        >
          {actionMessage}
        </div>
      ) : null}

      {actionError ? (
        <div
          role="alert"
          className="rounded-sm border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200"
        >
          {actionError}
        </div>
      ) : null}

      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-md border border-hairline bg-canvas-night-soft p-4">
          <h3 className="mb-3 text-sm font-medium text-ink-mute-2">Links</h3>
          <dl className="space-y-3 text-sm">
            <div>
              <dt className="text-xs uppercase tracking-wide text-ink-mute-2">
                Headscale
              </dt>
              <dd>
                <a
                  href={formatHostUrl(
                    tenant.headscale_host,
                    tenant.desired_config,
                  )}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex cursor-pointer items-center gap-1 text-primary hover:text-primary-soft"
                >
                  {tenant.headscale_host}
                  <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                </a>
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-ink-mute-2">
                Headplane
              </dt>
              <dd>
                <a
                  href={`${formatHostUrl(tenant.headplane_host, tenant.desired_config)}/admin/`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex cursor-pointer items-center gap-1 text-primary hover:text-primary-soft"
                >
                  {tenant.headplane_host}
                  <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                </a>
              </dd>
            </div>
          </dl>
        </div>

        <div className="rounded-md border border-hairline bg-canvas-night-soft p-4">
          <h3 className="mb-3 text-sm font-medium text-ink-mute-2">Details</h3>
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-ink-mute-2">Database</dt>
              <dd className="font-mono text-white">{tenant.db_name}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink-mute-2">Worker</dt>
              <dd className="font-mono text-xs text-white">
                {tenant.worker ?? '—'}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink-mute-2">Updated</dt>
              <dd className="text-white">{formatDateTime(tenant.updated_at)}</dd>
            </div>
          </dl>
        </div>
      </section>

      <TenantConnectPanel tenant={tenant} workerAssigned={Boolean(tenant.worker)} />

      <TenantBootstrapPanel
        bootstrapInfo={tenant.bootstrap_info}
        bootstrapStatus={tenant.bootstrap_status}
        bootstrapOutputRef={tenant.bootstrap_output_ref}
      />

      <TenantHealthPanel healthChecks={tenant.health_checks ?? []} />
    </div>
  )
}
