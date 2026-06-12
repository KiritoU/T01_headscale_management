import { ExternalLink } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { DataTable, type Column } from '../components/ui/DataTable'
import { ErrorState, LoadingState } from '../components/ui/PageState'
import { BootstrapStatusBadge } from '../components/ui/StatusBadge'
import { api } from '../lib/api'
import { formatHostUrl } from '../lib/format'
import type { BootstrapStatus, Tenant } from '../types'

const STATUS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'All statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'provisioning', label: 'Provisioning' },
  { value: 'bootstrapped', label: 'Bootstrapped' },
  { value: 'failed', label: 'Failed' },
]

export function TenantsPage() {
  const navigate = useNavigate()
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadTenants = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listTenants({
        bootstrap_status: statusFilter || undefined,
      })
      setTenants(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tenants')
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => {
    void loadTenants()
  }, [loadTenants])

  const columns = useMemo<Column<Tenant>[]>(
    () => [
      {
        key: 'slug',
        header: 'Slug',
        render: (row) => (
          <Link
            to={`/tenants/${row.id}`}
            className="font-medium text-primary hover:text-primary-soft"
            onClick={(event) => event.stopPropagation()}
          >
            {row.slug}
          </Link>
        ),
      },
      {
        key: 'bootstrap_status',
        header: 'Bootstrap status',
        render: (row) => (
          <BootstrapStatusBadge status={row.bootstrap_status as BootstrapStatus} />
        ),
      },
      {
        key: 'worker_name',
        header: 'Worker',
        render: (row) => (
          <span className="text-white">{row.worker_name ?? '—'}</span>
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
        key: 'headplane_host',
        header: 'Headplane URL',
        render: (row) => {
          const url = `${formatHostUrl(row.headplane_host, row.desired_config)}/admin/`
          return (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex cursor-pointer items-center gap-1 text-primary hover:text-primary-soft"
              onClick={(event) => event.stopPropagation()}
            >
              {url}
              <ExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden />
            </a>
          )
        },
      },
    ],
    [],
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-white">Tenants</h2>
          <p className="text-sm text-ink-mute-2">
            Headscale + Headplane tailnet instances
          </p>
        </div>
        <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
          Filter by status
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            className="cursor-pointer rounded-sm border border-hairline-strong bg-canvas-night-soft px-3 py-2 text-sm text-white focus:border-primary focus:outline-none"
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {loading ? (
        <LoadingState message="Loading tenants…" />
      ) : error ? (
        <ErrorState message={error} onRetry={() => void loadTenants()} />
      ) : (
        <DataTable
          columns={columns}
          rows={tenants}
          rowKey={(row) => row.id}
          onRowClick={(row) => navigate(`/tenants/${row.id}`)}
          emptyMessage="No tenants match the current filter."
        />
      )}
    </div>
  )
}
