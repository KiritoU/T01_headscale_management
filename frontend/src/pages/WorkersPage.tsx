import { Layers, Loader2, Plus, Trash2, Unplug } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AddWorkerModal } from '../components/workers/AddWorkerModal'
import { Button } from '../components/ui/Button'
import { DataTable, type Column } from '../components/ui/DataTable'
import { ErrorState, LoadingState } from '../components/ui/PageState'
import {
  BooleanBadge,
  ModuleBadge,
  WorkerStatusBadge,
} from '../components/ui/StatusBadge'
import { api } from '../lib/api'
import { formatDateTime } from '../lib/format'
import type { Worker, WorkerStatus } from '../types'

const WORKER_POLL_INTERVAL_MS = 10_000
const WORKER_ENROLL_POLL_INTERVAL_MS = 3000
const WORKER_ENROLL_POLL_MAX_MS = 10 * 60 * 1000
const WORKER_KNOWN_MODULES = ['docker'] as const

interface WorkerEnrollmentWatch {
  workerId: string
  workerName: string
  startedAt: number
}

type ConfirmAction =
  | { type: 'disconnect'; worker: Worker }
  | { type: 'delete'; worker: Worker }
  | null

function workerHasAgent(worker: Worker): boolean {
  return worker.status !== 'pending'
}

function canDisconnectWorker(worker: Worker): boolean {
  return worker.status === 'online' || worker.status === 'offline'
}

function canInstallDocker(worker: Worker): boolean {
  return (
    workerHasAgent(worker) &&
    !worker.docker_reachable &&
    !(worker.installed_modules?.includes('docker') ?? false)
  )
}

export function canManageTenants(worker: Worker): boolean {
  return worker.status === 'online' && worker.docker_reachable
}

export function WorkersPage() {
  const navigate = useNavigate()
  const [workers, setWorkers] = useState<Worker[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [installingWorkerId, setInstallingWorkerId] = useState<string | null>(
    null,
  )
  const [enrollmentWatch, setEnrollmentWatch] = useState<WorkerEnrollmentWatch | null>(
    null,
  )

  const loadWorkers = useCallback(async (options?: { silent?: boolean }) => {
    if (!options?.silent) {
      setLoading(true)
    }
    setError(null)
    try {
      const data = await api.listWorkers()
      setWorkers(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workers')
    } finally {
      if (!options?.silent) {
        setLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    void loadWorkers()
  }, [loadWorkers])

  useEffect(() => {
    const intervalId = setInterval(() => {
      void loadWorkers({ silent: true })
    }, WORKER_POLL_INTERVAL_MS)
    return () => clearInterval(intervalId)
  }, [loadWorkers])

  const startEnrollmentWatch = useCallback(
    (workerId: string, workerName: string) => {
      setEnrollmentWatch({
        workerId,
        workerName,
        startedAt: Date.now(),
      })
      void loadWorkers({ silent: true })
    },
    [loadWorkers],
  )

  useEffect(() => {
    if (!enrollmentWatch) {
      return
    }

    let cancelled = false

    const pollForWorkerOnline = async () => {
      if (Date.now() - enrollmentWatch.startedAt > WORKER_ENROLL_POLL_MAX_MS) {
        setEnrollmentWatch(null)
        return
      }

      try {
        const worker = await api.getWorker(enrollmentWatch.workerId)
        if (worker.status === 'pending' && !worker.last_heartbeat_at) {
          return
        }

        setEnrollmentWatch(null)
        setActionError(null)
        setActionMessage(
          `Worker ${worker.name} connected (${worker.status}${worker.hostname ? `, ${worker.hostname}` : ''}).`,
        )
        await loadWorkers({ silent: true })
      } catch {
        // Keep polling — transient network errors should not stop the watch.
      }
    }

    void pollForWorkerOnline()
    const intervalId = window.setInterval(() => {
      if (!cancelled) {
        void pollForWorkerOnline()
      }
    }, WORKER_ENROLL_POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [enrollmentWatch, loadWorkers])

  const installDocker = useCallback(async (worker: Worker) => {
    setActionError(null)
    setActionMessage(null)
    setInstallingWorkerId(worker.id)
    try {
      const result = await api.installWorkerModule(worker.id, 'docker')
      setActionMessage(
        `Install Docker queued for ${worker.name} (${result.id.slice(0, 8)}…, state: ${result.state})`,
      )
      await loadWorkers({ silent: true })
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : 'Failed to install Docker module',
      )
    } finally {
      setInstallingWorkerId(null)
    }
  }, [loadWorkers])

  const runConfirmedAction = async () => {
    if (!confirmAction) {
      return
    }

    const { worker } = confirmAction
    setActionLoading(true)
    setActionError(null)
    setActionMessage(null)

    try {
      if (confirmAction.type === 'disconnect') {
        await api.disconnectWorker(worker.id)
        setActionMessage(`Worker ${worker.name} disconnected.`)
      } else {
        await api.deleteWorker(worker.id)
        setActionMessage(`Worker ${worker.name} deleted.`)
      }
      setConfirmAction(null)
      await loadWorkers({ silent: true })
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : `Failed to ${confirmAction.type} worker`,
      )
    } finally {
      setActionLoading(false)
    }
  }

  const columns = useMemo<Column<Worker>[]>(
    () => [
      {
        key: 'name',
        header: 'Name',
        render: (row) => <span className="font-medium">{row.name}</span>,
      },
      {
        key: 'status',
        header: 'Status',
        render: (row) => (
          <WorkerStatusBadge status={row.status as WorkerStatus} />
        ),
      },
      {
        key: 'docker_reachable',
        header: 'Docker reachable',
        render: (row) => <BooleanBadge value={row.docker_reachable} />,
      },
      {
        key: 'modules',
        header: 'Modules',
        render: (row) => {
          const modules = (row.installed_modules ?? []).filter((name) =>
            WORKER_KNOWN_MODULES.includes(name as (typeof WORKER_KNOWN_MODULES)[number]),
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
        key: 'last_heartbeat_at',
        header: 'Last heartbeat',
        render: (row) => (
          <span className="text-ink-mute-2">
            {formatDateTime(row.last_heartbeat_at)}
          </span>
        ),
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
            {canManageTenants(row) ? (
              <Button
                variant="secondary"
                className="px-3 py-1.5 text-xs"
                disabled={actionLoading || installingWorkerId !== null}
                onClick={() => navigate(`/workers/${row.id}/tenants`)}
              >
                <Layers className="h-3.5 w-3.5" aria-hidden />
                Tenants
              </Button>
            ) : null}
            {canDisconnectWorker(row) ? (
              <Button
                variant="secondary"
                className="px-3 py-1.5 text-xs"
                disabled={actionLoading || installingWorkerId !== null}
                onClick={() =>
                  setConfirmAction({ type: 'disconnect', worker: row })
                }
              >
                <Unplug className="h-3.5 w-3.5" aria-hidden />
                Disconnect
              </Button>
            ) : null}
            {canInstallDocker(row) ? (
              <Button
                variant="secondary"
                className="px-3 py-1.5 text-xs"
                disabled={
                  installingWorkerId !== null ||
                  actionLoading ||
                  confirmAction !== null
                }
                onClick={() => void installDocker(row)}
              >
                {installingWorkerId === row.id ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : null}
                Install Docker
              </Button>
            ) : null}
            <Button
              variant="secondary"
              className="px-3 py-1.5 text-xs text-red-200 hover:border-red-500/40 hover:bg-red-500/10"
              disabled={actionLoading || installingWorkerId !== null}
              onClick={() => setConfirmAction({ type: 'delete', worker: row })}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden />
              Delete
            </Button>
          </div>
        ),
      },
    ],
    [actionLoading, confirmAction, installDocker, installingWorkerId, navigate],
  )

  const confirmTitle =
    confirmAction?.type === 'disconnect'
      ? 'Disconnect worker'
      : confirmAction?.type === 'delete'
        ? 'Delete worker'
        : ''

  const confirmBody =
    confirmAction?.type === 'disconnect'
      ? `Revoke the agent token and shut down ${confirmAction.worker.name}? The worker record stays but the agent must re-enroll.`
      : confirmAction?.type === 'delete'
        ? `Permanently delete ${confirmAction.worker.name}? This only succeeds when no tenants are assigned.`
        : ''

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-white">Workers</h2>
          <p className="text-sm text-ink-mute-2">
            VPS hosts running tenant stacks
          </p>
        </div>
        <Button onClick={() => setModalOpen(true)}>
          <Plus className="h-4 w-4" aria-hidden />
          Add new worker
        </Button>
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
        <LoadingState message="Loading workers…" />
      ) : error ? (
        <ErrorState message={error} onRetry={() => void loadWorkers()} />
      ) : (
        <DataTable
          columns={columns}
          rows={workers}
          rowKey={(row) => row.id}
          onRowClick={(row) => {
            if (canManageTenants(row)) {
              navigate(`/workers/${row.id}/tenants`)
            }
          }}
          emptyMessage="No workers registered yet."
        />
      )}

      <AddWorkerModal
        open={modalOpen}
        watchingEnrollment={enrollmentWatch !== null}
        onClose={() => setModalOpen(false)}
        onEnrollmentTokenCreated={(workerId, workerName) =>
          startEnrollmentWatch(workerId, workerName)
        }
      />

      {confirmAction ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          role="presentation"
        >
          <button
            type="button"
            aria-label="Close dialog"
            className="absolute inset-0 cursor-pointer bg-black/60"
            onClick={() => {
              if (!actionLoading) {
                setConfirmAction(null)
              }
            }}
          />
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="worker-confirm-title"
            aria-describedby="worker-confirm-body"
            className="relative z-10 w-full max-w-md rounded-md border border-hairline bg-canvas-night-soft shadow-xl"
          >
            <div className="border-b border-hairline px-5 py-4">
              <h2
                id="worker-confirm-title"
                className="text-base font-semibold text-white"
              >
                {confirmTitle}
              </h2>
            </div>
            <div className="px-5 py-4">
              <p id="worker-confirm-body" className="text-sm text-ink-mute-2">
                {confirmBody}
              </p>
            </div>
            <div className="flex justify-end gap-2 border-t border-hairline px-5 py-4">
              <Button
                variant="secondary"
                disabled={actionLoading}
                onClick={() => setConfirmAction(null)}
              >
                Cancel
              </Button>
              <Button
                disabled={actionLoading}
                className={
                  confirmAction.type === 'delete'
                    ? 'bg-red-600 text-white hover:bg-red-500 disabled:bg-red-600/40'
                    : undefined
                }
                onClick={() => void runConfirmedAction()}
              >
                {actionLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : null}
                {confirmAction.type === 'disconnect' ? 'Disconnect' : 'Delete'}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
