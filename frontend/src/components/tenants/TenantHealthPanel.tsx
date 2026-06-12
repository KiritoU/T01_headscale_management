import { DataTable, type Column } from '../ui/DataTable'
import { BooleanBadge, StatusBadge } from '../ui/StatusBadge'
import { formatDateTime } from '../../lib/format'
import { TENANT_VERIFY_INTERVAL_MS } from '../../lib/tenantLifecycle'
import type { TenantHealth } from '../../types'

const verifyIntervalSeconds = TENANT_VERIFY_INTERVAL_MS / 1000

const healthColumns: Column<TenantHealth>[] = [
  {
    key: 'probed_at',
    header: 'Probed at',
    render: (row) => formatDateTime(row.probed_at),
  },
  {
    key: 'healthy',
    header: 'Healthy',
    render: (row) => <BooleanBadge value={row.healthy} />,
  },
  {
    key: 'latency_ms',
    header: 'Latency (ms)',
    render: (row) => row.latency_ms,
  },
  {
    key: 'error_message',
    header: 'Error',
    render: (row) => (
      <span className="line-clamp-2 text-ink-mute-2">{row.error_message || '—'}</span>
    ),
  },
]

interface TenantHealthPanelProps {
  healthChecks: TenantHealth[]
}

export function TenantHealthPanel({ healthChecks }: TenantHealthPanelProps) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-white">Recent health checks</h3>
        <StatusBadge
          label={`${healthChecks.length} / 5`}
          variant="neutral"
        />
      </div>
      <DataTable
        columns={healthColumns}
        rows={healthChecks}
        rowKey={(row) => row.id}
        emptyMessage={`No health checks recorded yet. Probes run automatically every ${verifyIntervalSeconds}s while this page is open.`}
      />
    </section>
  )
}
