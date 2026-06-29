import { Activity, ArrowLeft, Layers } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ResourceMetricsPanel } from '../components/metrics/ResourceMetricsPanel'
import { ErrorState, LoadingState } from '../components/ui/PageState'
import { WorkerStatusBadge } from '../components/ui/StatusBadge'
import { api } from '../lib/api'
import type { Worker } from '../types'

export function WorkerMetricsPage() {
  const { workerId } = useParams<{ workerId: string }>()
  const [worker, setWorker] = useState<Worker | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadWorker = useCallback(async () => {
    if (!workerId) {
      setError('Worker not found')
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await api.getWorker(workerId)
      setWorker(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load worker')
    } finally {
      setLoading(false)
    }
  }, [workerId])

  useEffect(() => {
    void loadWorker()
  }, [loadWorker])

  const fetchMetrics = useCallback(() => {
    if (!workerId) {
      return Promise.reject(new Error('Worker not found'))
    }
    return api.getWorkerMetrics(workerId)
  }, [workerId])

  if (loading) {
    return <LoadingState message="Loading worker…" />
  }

  if (error || !worker) {
    return (
      <ErrorState
        message={error ?? 'Worker not found'}
        onRetry={() => void loadWorker()}
      />
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-3">
          <Link
            to="/workers"
            className="inline-flex items-center gap-2 text-sm text-ink-mute-2 transition-colors hover:text-white"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden />
            Back to workers
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold text-white">{worker.name}</h1>
            <WorkerStatusBadge status={worker.status} />
          </div>
          <p className="text-sm text-ink-mute-2">
            {worker.hostname || 'No hostname'} · {worker.public_ip ?? 'No public IP'}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            to={`/workers/${worker.id}/tenants`}
            className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-sm border border-hairline-strong bg-canvas-night-soft px-3 py-2 text-sm font-medium text-white transition-colors hover:border-primary/40 hover:bg-white/5"
          >
            <Layers className="h-4 w-4" aria-hidden />
            Tenants
          </Link>
        </div>
      </div>

      <div className="flex items-center gap-2 text-sm text-ink-mute-2">
        <Activity className="h-4 w-4 text-primary" aria-hidden />
        Live host metrics from agent heartbeats
      </div>

      <ResourceMetricsPanel
        title={`${worker.name} resources`}
        fetcher={fetchMetrics}
        emptyMessage={
          worker.status === 'pending'
            ? 'Worker has not enrolled yet. Metrics appear after the agent connects.'
            : 'No metrics yet. Metrics appear after the worker agent sends its next heartbeat.'
        }
      />
    </div>
  )
}
