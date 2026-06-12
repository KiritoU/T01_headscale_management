import { Loader2, Plus, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AddGatewayModal } from '../components/gateways/AddGatewayModal'
import { Button } from '../components/ui/Button'
import { DataTable, type Column } from '../components/ui/DataTable'
import { ErrorState, LoadingState } from '../components/ui/PageState'
import {
  GatewayStatusBadge,
  ModuleBadge,
  OnlineIndicator,
} from '../components/ui/StatusBadge'
import { api } from '../lib/api'
import type { Gateway, GatewayStatus, Tenant } from '../types'

const GATEWAY_ENROLL_POLL_INTERVAL_MS = 3000
const GATEWAY_ENROLL_POLL_MAX_MS = 10 * 60 * 1000

interface EnrollmentWatch {
  tenantId: string
  knownGatewayIds: Set<string>
  startedAt: number
}

function isGatewayOnline(gateway: Gateway): boolean {
  return gateway.status === 'online'
}

export function GatewaysPage() {
  const navigate = useNavigate()
  const [gateways, setGateways] = useState<Gateway[]>([])
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [tenantFilter, setTenantFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [gatewayToDelete, setGatewayToDelete] = useState<Gateway | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [enrollmentWatch, setEnrollmentWatch] = useState<EnrollmentWatch | null>(
    null,
  )

  const loadGateways = useCallback(async (options: { silent?: boolean } = {}) => {
    if (!options.silent) {
      setLoading(true)
    }
    setError(null)
    try {
      const data = await api.listGateways({
        tenant_id: tenantFilter || undefined,
      })
      setGateways(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load gateways')
    } finally {
      if (!options.silent) {
        setLoading(false)
      }
    }
  }, [tenantFilter])

  const deleteGateway = async () => {
    if (!gatewayToDelete) {
      return
    }
    setDeleting(true)
    setActionError(null)
    setActionMessage(null)
    try {
      await api.deleteGateway(gatewayToDelete.id)
      setActionMessage(
        `Gateway ${gatewayToDelete.hostname || gatewayToDelete.id.slice(0, 8)} deleted.`,
      )
      setGatewayToDelete(null)
      await loadGateways({ silent: true })
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : 'Failed to delete gateway',
      )
      setGatewayToDelete(null)
    } finally {
      setDeleting(false)
    }
  }

  const loadTenants = useCallback(async () => {
    try {
      const data = await api.listTenants()
      setTenants(data)
    } catch {
      setTenants([])
    }
  }, [])

  useEffect(() => {
    void loadTenants()
  }, [loadTenants])

  useEffect(() => {
    void loadGateways()
  }, [loadGateways])

  const startEnrollmentWatch = useCallback(async (tenantId: string) => {
    try {
      const existing = await api.listGateways({ tenant_id: tenantId })
      setEnrollmentWatch({
        tenantId,
        knownGatewayIds: new Set(existing.map((gateway) => gateway.id)),
        startedAt: Date.now(),
      })
    } catch {
      setEnrollmentWatch({
        tenantId,
        knownGatewayIds: new Set(),
        startedAt: Date.now(),
      })
    }
  }, [])

  useEffect(() => {
    if (!enrollmentWatch) {
      return
    }

    let cancelled = false

    const pollForNewGateway = async () => {
      if (Date.now() - enrollmentWatch.startedAt > GATEWAY_ENROLL_POLL_MAX_MS) {
        setEnrollmentWatch(null)
        return
      }

      try {
        const data = await api.listGateways({
          tenant_id: enrollmentWatch.tenantId,
        })
        const newcomer = data.find(
          (gateway) => !enrollmentWatch.knownGatewayIds.has(gateway.id),
        )
        if (!newcomer) {
          return
        }

        setEnrollmentWatch(null)
        setActionError(null)
        setActionMessage(
          `Gateway ${newcomer.hostname || newcomer.id.slice(0, 8)} enrolled (${newcomer.tenant_slug}).`,
        )
        await loadGateways({ silent: true })
      } catch {
        // Keep polling — transient network errors should not stop the watch.
      }
    }

    void pollForNewGateway()
    const intervalId = window.setInterval(() => {
      if (!cancelled) {
        void pollForNewGateway()
      }
    }, GATEWAY_ENROLL_POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [enrollmentWatch, loadGateways])

  const columns = useMemo<Column<Gateway>[]>(
    () => [
      {
        key: 'hostname',
        header: 'Hostname',
        render: (row) => (
          <Link
            to={`/gateways/${row.id}`}
            className="font-medium text-primary hover:text-primary-soft"
            onClick={(event) => event.stopPropagation()}
          >
            {row.hostname || '—'}
          </Link>
        ),
      },
      {
        key: 'tenant_slug',
        header: 'Tenant',
        render: (row) => (
          <span className="font-mono text-xs text-ink-mute-2">{row.tenant_slug}</span>
        ),
      },
      {
        key: 'status',
        header: 'Status',
        render: (row) => (
          <GatewayStatusBadge status={row.status as GatewayStatus} />
        ),
      },
      {
        key: 'online',
        header: 'Online',
        render: (row) => <OnlineIndicator online={isGatewayOnline(row)} />,
      },
      {
        key: 'tags',
        header: 'Tags',
        render: (row) => (
          <span className="text-ink-mute-2">
            {row.custom_tags.length > 0 ? row.custom_tags.join(', ') : '—'}
          </span>
        ),
      },
      {
        key: 'modules',
        header: 'Modules',
        render: (row) => {
          const modules = row.installed_modules.filter(
            (name) => name === 'tailscale' || name === 'nmap',
          )
          if (modules.length === 0) {
            return <span className="text-ink-mute-2">—</span>
          }
          return (
            <span className="flex flex-wrap gap-1">
              {modules.map((moduleName) => (
                <ModuleBadge key={moduleName} moduleName={moduleName} />
              ))}
            </span>
          )
        },
      },
      {
        key: 'actions',
        header: 'Actions',
        render: (row) => (
          <div
            className="flex flex-wrap gap-2"
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => event.stopPropagation()}
          >
            <Button
              variant="secondary"
              className="px-3 py-1.5 text-xs text-red-200 hover:border-red-500/40 hover:bg-red-500/10"
              disabled={deleting}
              onClick={() => setGatewayToDelete(row)}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden />
              Delete
            </Button>
          </div>
        ),
      },
    ],
    [deleting],
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-white">Gateways</h2>
          <p className="text-sm text-ink-mute-2">
            Subnet router agents per tenant tailnet
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <Button onClick={() => setModalOpen(true)}>
            <Plus className="h-4 w-4" aria-hidden />
            Enroll gateway
          </Button>
          <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
            Filter by tenant
            <select
              value={tenantFilter}
              onChange={(event) => setTenantFilter(event.target.value)}
              className="cursor-pointer rounded-sm border border-hairline-strong bg-canvas-night-soft px-3 py-2 text-sm text-white focus:border-primary focus:outline-none"
            >
              <option value="">All tenants</option>
              {tenants.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>
                  {tenant.slug}
                </option>
              ))}
            </select>
          </label>
        </div>
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

      {loading ? (
        <LoadingState message="Loading gateways…" />
      ) : error ? (
        <ErrorState message={error} onRetry={() => void loadGateways()} />
      ) : (
        <DataTable
          columns={columns}
          rows={gateways}
          rowKey={(row) => row.id}
          onRowClick={(row) => navigate(`/gateways/${row.id}`)}
          emptyMessage="No gateways match the current filter."
        />
      )}

      <AddGatewayModal
        open={modalOpen}
        tenants={tenants}
        defaultTenantId={tenantFilter}
        watchingEnrollment={enrollmentWatch !== null}
        onClose={() => setModalOpen(false)}
        onEnrollmentTokenCreated={(tenantId) => void startEnrollmentWatch(tenantId)}
      />

      {gatewayToDelete ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          role="presentation"
        >
          <button
            type="button"
            aria-label="Close dialog"
            className="absolute inset-0 cursor-pointer bg-black/60"
            onClick={() => {
              if (!deleting) {
                setGatewayToDelete(null)
              }
            }}
          />
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="gateway-list-delete-title"
            aria-describedby="gateway-list-delete-body"
            className="relative z-10 w-full max-w-md rounded-md border border-hairline bg-canvas-night-soft shadow-xl"
          >
            <div className="border-b border-hairline px-5 py-4">
              <h2
                id="gateway-list-delete-title"
                className="text-base font-semibold text-white"
              >
                Delete gateway
              </h2>
            </div>
            <div className="px-5 py-4">
              <p id="gateway-list-delete-body" className="text-sm text-ink-mute-2">
                Permanently delete{' '}
                <span className="font-medium text-white">
                  {gatewayToDelete.hostname || 'this gateway'}
                </span>{' '}
                ({gatewayToDelete.tenant_slug})? The enrolled agent token will be
                revoked.
              </p>
            </div>
            <div className="flex justify-end gap-2 border-t border-hairline px-5 py-4">
              <Button
                variant="secondary"
                disabled={deleting}
                onClick={() => setGatewayToDelete(null)}
              >
                Cancel
              </Button>
              <Button
                disabled={deleting}
                className="bg-red-600 text-white hover:bg-red-500 disabled:bg-red-600/40"
                onClick={() => void deleteGateway()}
              >
                {deleting ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : null}
                Delete
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
