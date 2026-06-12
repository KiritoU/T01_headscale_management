import {
  ArrowLeft,
  Layers,
  Loader2,
  Play,
  Plus,
  Trash2,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Button } from '../components/ui/Button'
import { DataTable, type Column } from '../components/ui/DataTable'
import { ErrorState, LoadingState } from '../components/ui/PageState'
import {
  BootstrapStatusBadge,
  RuntimeStatusBadge,
  WorkerStatusBadge,
} from '../components/ui/StatusBadge'
import { api } from '../lib/api'
import type {
  BootstrapStatus,
  RuntimeStatus,
  Worker,
  WorkerStatus,
  WorkerTenant,
  WorkerTenantSummary,
} from '../types'

const TENANT_POLL_INTERVAL_MS = 10_000

type TenantAction =
  | 'provision'
  | 'start'
  | 'stop'
  | 'verify'
  | 'bootstrap'
  | 'remove'

type ConfirmDelete = { tenant: WorkerTenant } | null

function formatActionMessage(
  action: TenantAction,
  slug: string,
  result: { command_id?: string | null; skipped?: boolean },
): string {
  if (result.skipped) {
    return `${action} for ${slug} already queued.`
  }
  if (result.command_id) {
    return `${action.charAt(0).toUpperCase()}${action.slice(1)} queued for ${slug} (${result.command_id.slice(0, 8)}…).`
  }
  return `${action.charAt(0).toUpperCase()}${action.slice(1)} dispatched for ${slug}.`
}

function SummaryCard({
  label,
  value,
  accent = 'text-white',
}: {
  label: string
  value: number
  accent?: string
}) {
  return (
    <div className="rounded-md border border-hairline bg-canvas-night-soft p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-mute-2">
        {label}
      </p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${accent}`}>
        {value}
      </p>
    </div>
  )
}

export function WorkerTenantsPage() {
  const navigate = useNavigate()
  const { workerId } = useParams<{ workerId: string }>()
  const [worker, setWorker] = useState<Worker | null>(null)
  const [summary, setSummary] = useState<WorkerTenantSummary | null>(null)
  const [tenants, setTenants] = useState<WorkerTenant[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [bulkModalOpen, setBulkModalOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<ConfirmDelete>(null)
  const [bulkLoading, setBulkLoading] = useState(false)
  const [bulkProvisionLoading, setBulkProvisionLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [deleteLoading, setDeleteLoading] = useState(false)

  const [suffix, setSuffix] = useState('team')
  const [startNumber, setStartNumber] = useState(1)
  const [count, setCount] = useState(1)
  const [baseDomain, setBaseDomain] = useState('')
  const [production, setProduction] = useState(false)

  const loadData = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!workerId) {
        return
      }
      if (!options?.silent) {
        setLoading(true)
      }
      setError(null)
      try {
        const [workerData, summaryData, tenantData] = await Promise.all([
          api.getWorker(workerId),
          api.getWorkerTenantSummary(workerId),
          api.listWorkerTenants(workerId),
        ])
        setWorker(workerData)
        setSummary(summaryData)
        setTenants(tenantData)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load worker tenants')
      } finally {
        if (!options?.silent) {
          setLoading(false)
        }
      }
    },
    [workerId],
  )

  useEffect(() => {
    void loadData()
  }, [loadData])

  useEffect(() => {
    if (bulkModalOpen || confirmDelete) {
      return
    }
    const intervalId = setInterval(() => {
      void loadData({ silent: true })
    }, TENANT_POLL_INTERVAL_MS)
    return () => clearInterval(intervalId)
  }, [bulkModalOpen, confirmDelete, loadData])

  const runTenantAction = useCallback(
    async (tenant: WorkerTenant, action: Exclude<TenantAction, 'remove'>) => {
      if (!workerId) {
        return
      }
      const actionKey = `${tenant.id}:${action}`
      setActionLoading(actionKey)
      setActionError(null)
      setActionMessage(null)
      try {
        let result
        switch (action) {
          case 'provision':
            result = await api.provisionWorkerTenant(workerId, tenant.id)
            break
          case 'start':
            result = await api.startWorkerTenant(workerId, tenant.id)
            break
          case 'stop':
            result = await api.stopWorkerTenant(workerId, tenant.id)
            break
          case 'verify':
            result = await api.verifyWorkerTenant(workerId, tenant.id)
            break
          case 'bootstrap':
            result = await api.bootstrapWorkerTenant(workerId, tenant.id)
            break
        }
        setActionMessage(formatActionMessage(action, tenant.slug, result))
        await loadData({ silent: true })
      } catch (err) {
        setActionError(
          err instanceof Error
            ? err.message
            : `Failed to ${action} tenant ${tenant.slug}`,
        )
      } finally {
        setActionLoading(null)
      }
    },
    [loadData, workerId],
  )

  const handleBulkCreate = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!workerId) {
      return
    }
    const trimmedSuffix = suffix.trim()
    const trimmedDomain = baseDomain.trim()
    if (!trimmedSuffix || !trimmedDomain || count < 1 || startNumber < 1) {
      setActionError('Suffix, base domain, start number, and count are required.')
      return
    }

    setBulkLoading(true)
    setActionError(null)
    setActionMessage(null)
    try {
      const created = await api.bulkCreateWorkerTenants(workerId, {
        suffix: trimmedSuffix,
        start_number: startNumber,
        count,
        base_domain: trimmedDomain,
        production,
      })
      setActionMessage(
        `Created ${created.length} tenant${created.length === 1 ? '' : 's'} (${created.map((t) => t.slug).join(', ')}).`,
      )
      setBulkModalOpen(false)
      await loadData({ silent: true })
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : 'Failed to bulk create tenants',
      )
    } finally {
      setBulkLoading(false)
    }
  }

  const handleBulkProvision = async () => {
    if (!workerId) {
      return
    }
    setBulkProvisionLoading(true)
    setActionError(null)
    setActionMessage(null)
    try {
      const results = await api.bulkProvisionWorkerTenants(workerId)
      const queued = results.filter((result) => !result.skipped).length
      const skipped = results.length - queued
      setActionMessage(
        results.length === 0
          ? 'No pending tenants to provision.'
          : `Provision queued for ${queued} tenant${queued === 1 ? '' : 's'}${skipped > 0 ? ` (${skipped} already queued)` : ''}.`,
      )
      await loadData({ silent: true })
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : 'Failed to provision pending tenants',
      )
    } finally {
      setBulkProvisionLoading(false)
    }
  }

  const handleDeleteTenant = async () => {
    if (!workerId || !confirmDelete) {
      return
    }
    const { tenant } = confirmDelete
    setDeleteLoading(true)
    setActionError(null)
    setActionMessage(null)
    try {
      await api.removeWorkerTenant(workerId, tenant.id)
      setActionMessage(`Removed tenant ${tenant.slug}.`)
      setConfirmDelete(null)
      await loadData({ silent: true })
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : `Failed to remove ${tenant.slug}`,
      )
    } finally {
      setDeleteLoading(false)
    }
  }

  const pendingRuntimeCount = summary?.runtime_status.pending ?? 0

  const columns = useMemo<Column<WorkerTenant>[]>(
    () => [
      {
        key: 'slug',
        header: 'Slug',
        render: (row) => <span className="font-medium">{row.slug}</span>,
      },
      {
        key: 'bootstrap_status',
        header: 'Bootstrap status',
        render: (row) => (
          <BootstrapStatusBadge
            status={row.bootstrap_status as BootstrapStatus}
          />
        ),
      },
      {
        key: 'runtime_status',
        header: 'Runtime status',
        render: (row) => (
          <RuntimeStatusBadge status={row.runtime_status as RuntimeStatus} />
        ),
      },
      {
        key: 'headscale_host',
        header: 'Headscale host',
        render: (row) => (
          <span className="text-ink-mute-2">{row.headscale_host}</span>
        ),
      },
      {
        key: 'actions',
        header: 'Actions',
        render: (row) => {
          const isBusy = actionLoading?.startsWith(`${row.id}:`) ?? false
          const actionDisabled =
            isBusy || bulkProvisionLoading || deleteLoading || bulkLoading

          return (
            <div
              className="flex flex-wrap gap-1.5"
              onClick={(event) => event.stopPropagation()}
              onKeyDown={(event) => event.stopPropagation()}
            >
              {(
                [
                  ['provision', 'Provision'],
                  ['start', 'Start'],
                  ['stop', 'Stop'],
                  ['verify', 'Verify'],
                  ['bootstrap', 'Bootstrap'],
                ] as const
              ).map(([action, label]) => (
                <Button
                  key={action}
                  variant="secondary"
                  className="px-2 py-1 text-xs"
                  disabled={actionDisabled}
                  onClick={() => void runTenantAction(row, action)}
                >
                  {actionLoading === `${row.id}:${action}` ? (
                    <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                  ) : null}
                  {label}
                </Button>
              ))}
              <Button
                variant="secondary"
                className="px-2 py-1 text-xs text-red-200 hover:border-red-500/40 hover:bg-red-500/10"
                disabled={actionDisabled || confirmDelete !== null}
                onClick={() => setConfirmDelete({ tenant: row })}
              >
                <Trash2 className="h-3 w-3" aria-hidden />
                Remove
              </Button>
            </div>
          )
        },
      },
    ],
    [
      actionLoading,
      bulkLoading,
      bulkProvisionLoading,
      confirmDelete,
      deleteLoading,
      runTenantAction,
    ],
  )

  if (!workerId) {
    return <ErrorState message="Worker ID is missing." />
  }

  if (loading) {
    return <LoadingState message="Loading worker tenants…" />
  }

  if (error || !worker) {
    return (
      <div className="space-y-4">
        <Link
          to="/workers"
          className="inline-flex cursor-pointer items-center gap-2 text-sm text-ink-mute-2 hover:text-primary"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
          Back to workers
        </Link>
        <ErrorState
          message={error ?? 'Worker not found'}
          onRetry={() => void loadData()}
        />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <Link
            to="/workers"
            className="inline-flex cursor-pointer items-center gap-2 text-sm text-ink-mute-2 hover:text-primary"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden />
            Back to workers
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-lg font-semibold text-white">{worker.name}</h2>
            <WorkerStatusBadge status={worker.status as WorkerStatus} />
          </div>
          <p className="text-sm text-ink-mute-2">
            Tenant stacks on {worker.hostname}
          </p>
        </div>
        <Button onClick={() => setBulkModalOpen(true)}>
          <Plus className="h-4 w-4" aria-hidden />
          Bulk create
        </Button>
      </div>

      {summary ? (
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard label="Total" value={summary.total} />
          <SummaryCard
            label="Running"
            value={summary.runtime_status.running ?? 0}
            accent="text-primary"
          />
          <SummaryCard
            label="Bootstrapped"
            value={summary.bootstrap_status.bootstrapped ?? 0}
            accent="text-primary"
          />
          <SummaryCard
            label="Pending"
            value={summary.runtime_status.pending ?? 0}
          />
        </section>
      ) : null}

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

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-hairline bg-canvas-night-soft px-4 py-3">
        <div className="flex items-center gap-2 text-sm text-ink-mute-2">
          <Layers className="h-4 w-4 text-primary" aria-hidden />
          <span>
            {tenants.length} tenant{tenants.length === 1 ? '' : 's'} assigned
          </span>
        </div>
        <Button
          variant="secondary"
          disabled={
            bulkProvisionLoading ||
            pendingRuntimeCount === 0 ||
            bulkLoading ||
            deleteLoading
          }
          onClick={() => void handleBulkProvision()}
        >
          {bulkProvisionLoading ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Play className="h-4 w-4" aria-hidden />
          )}
          Provision all pending
          {pendingRuntimeCount > 0 ? ` (${pendingRuntimeCount})` : ''}
        </Button>
      </div>

      <DataTable
        columns={columns}
        rows={tenants}
        rowKey={(row) => row.id}
        emptyMessage="No tenants on this worker yet. Use bulk create to add tenants."
        onRowClick={(row) =>
          navigate(`/workers/${workerId}/tenants/${row.id}`)
        }
      />

      {bulkModalOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          role="presentation"
        >
          <button
            type="button"
            aria-label="Close dialog"
            className="absolute inset-0 cursor-pointer bg-black/60"
            onClick={() => {
              if (!bulkLoading) {
                setBulkModalOpen(false)
              }
            }}
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="bulk-create-title"
            className="relative z-10 w-full max-w-md rounded-md border border-hairline bg-canvas-night-soft shadow-xl"
          >
            <form onSubmit={(event) => void handleBulkCreate(event)}>
              <div className="border-b border-hairline px-5 py-4">
                <h2
                  id="bulk-create-title"
                  className="text-base font-semibold text-white"
                >
                  Bulk create tenants
                </h2>
                <p className="mt-1 text-sm text-ink-mute-2">
                  Same naming as legacy generate-multi-tenants.sh
                </p>
              </div>
              <div className="space-y-4 px-5 py-4">
                <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
                  Suffix
                  <input
                    value={suffix}
                    onChange={(event) => setSuffix(event.target.value)}
                    placeholder="team"
                    className="rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none"
                  />
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
                    Start number
                    <input
                      type="number"
                      min={1}
                      value={startNumber}
                      onChange={(event) =>
                        setStartNumber(Number(event.target.value))
                      }
                      className="rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none"
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
                    Count
                    <input
                      type="number"
                      min={1}
                      max={100}
                      value={count}
                      onChange={(event) => setCount(Number(event.target.value))}
                      className="rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none"
                    />
                  </label>
                </div>
                <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
                  Base domain
                  <input
                    value={baseDomain}
                    onChange={(event) => setBaseDomain(event.target.value)}
                    placeholder="example.com"
                    className="rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none"
                  />
                </label>
                <label className="flex cursor-pointer items-start gap-3 rounded-sm border border-hairline bg-canvas-night px-3 py-3">
                  <input
                    type="checkbox"
                    checked={production}
                    onChange={(event) => setProduction(event.target.checked)}
                    className="mt-0.5 h-4 w-4 rounded border-hairline-strong bg-canvas-night text-primary focus:ring-primary"
                  />
                  <span className="flex flex-col gap-1">
                    <span className="text-sm font-medium text-white">
                      Production
                    </span>
                    <span className="text-xs text-ink-mute-2">
                      {production
                        ? 'Traefik terminates TLS with Let’s Encrypt (Cloudflare DNS). Requires ACME_EMAIL and CF_DNS_API_TOKEN in the worker stack .env.'
                        : 'Traefik listens on HTTP port 80 only. Map domains via /etc/hosts for local testing.'}
                    </span>
                  </span>
                </label>
                <p className="text-xs text-ink-mute-2">
                  Creates slugs like {suffix.trim() || 'team'}-{startNumber} …{' '}
                  {suffix.trim() || 'team'}-{startNumber + Math.max(count, 1) - 1}
                </p>
              </div>
              <div className="flex justify-end gap-2 border-t border-hairline px-5 py-4">
                <Button
                  type="button"
                  variant="secondary"
                  disabled={bulkLoading}
                  onClick={() => setBulkModalOpen(false)}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={bulkLoading}>
                  {bulkLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : null}
                  Create
                </Button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {confirmDelete ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          role="presentation"
        >
          <button
            type="button"
            aria-label="Close dialog"
            className="absolute inset-0 cursor-pointer bg-black/60"
            onClick={() => {
              if (!deleteLoading) {
                setConfirmDelete(null)
              }
            }}
          />
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="delete-tenant-title"
            aria-describedby="delete-tenant-body"
            className="relative z-10 w-full max-w-md rounded-md border border-hairline bg-canvas-night-soft shadow-xl"
          >
            <div className="border-b border-hairline px-5 py-4">
              <h2
                id="delete-tenant-title"
                className="text-base font-semibold text-white"
              >
                Remove tenant
              </h2>
            </div>
            <div className="px-5 py-4">
              <p id="delete-tenant-body" className="text-sm text-ink-mute-2">
                Permanently remove {confirmDelete.tenant.slug}? Running stacks
                are stopped first.
              </p>
            </div>
            <div className="flex justify-end gap-2 border-t border-hairline px-5 py-4">
              <Button
                variant="secondary"
                disabled={deleteLoading}
                onClick={() => setConfirmDelete(null)}
              >
                Cancel
              </Button>
              <Button
                disabled={deleteLoading}
                className="bg-red-600 text-white hover:bg-red-500 disabled:bg-red-600/40"
                onClick={() => void handleDeleteTenant()}
              >
                {deleteLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Trash2 className="h-4 w-4" aria-hidden />
                )}
                Remove
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
