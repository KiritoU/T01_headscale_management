import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ErrorState, LoadingState } from '../ui/PageState'
import {
  formatBytes,
  formatBytesPerSec,
  formatDateTime,
  formatPercent,
  formatUptime,
} from '../../lib/format'
import type { ResourceMetricsResponse, ResourceSample } from '../../types'

const METRICS_POLL_INTERVAL_MS = 15_000
const CHART_COLOR = '#3ecf8e'

interface ChartPoint {
  time: string
  label: string
  value: number | null
}

function MetricStatCard({
  label,
  value,
  detail,
  accent = 'text-white',
}: {
  label: string
  value: string
  detail?: string
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
      {detail ? (
        <p className="mt-1 text-xs text-ink-mute-2">{detail}</p>
      ) : null}
    </div>
  )
}

function MetricAreaChart({
  title,
  subtitle,
  data,
  valueFormatter,
  domain,
}: {
  title: string
  subtitle?: string
  data: ChartPoint[]
  valueFormatter: (value: number) => string
  domain?: [number, number]
}) {
  const hasData = data.some((point) => point.value !== null)

  return (
    <div className="rounded-md border border-hairline bg-canvas-night-soft p-4">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-white">{title}</h3>
          {subtitle ? (
            <p className="mt-1 text-xs text-ink-mute-2">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {!hasData ? (
        <p className="py-10 text-center text-sm text-ink-mute-2">
          Waiting for metric samples…
        </p>
      ) : (
        <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id={`fill-${title}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={CHART_COLOR} stopOpacity={0.35} />
                  <stop offset="95%" stopColor={CHART_COLOR} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
              <XAxis
                dataKey="label"
                tick={{ fill: '#8b9bb4', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                minTickGap={24}
              />
              <YAxis
                domain={domain ?? ['auto', 'auto']}
                tick={{ fill: '#8b9bb4', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={48}
                tickFormatter={(value: number) => valueFormatter(value)}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1c1f26',
                  border: '1px solid rgba(255,255,255,0.08)',
                  borderRadius: 8,
                  color: '#fff',
                }}
                labelFormatter={(_, payload) => {
                  const point = payload?.[0]?.payload as ChartPoint | undefined
                  return point ? formatDateTime(point.time) : ''
                }}
                formatter={(value: number) => [valueFormatter(value), title]}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke={CHART_COLOR}
                fill={`url(#fill-${title})`}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

function toChartPoints(
  samples: ResourceSample[],
  pickValue: (sample: ResourceSample) => number | null,
): ChartPoint[] {
  return samples.map((sample) => ({
    time: sample.sampled_at,
    label: new Intl.DateTimeFormat(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }).format(new Date(sample.sampled_at)),
    value: pickValue(sample),
  }))
}

function buildStatCards(current: ResourceSample | null) {
  const memDetail =
    current?.mem_used_bytes != null && current.mem_total_bytes != null
      ? `${formatBytes(current.mem_used_bytes)} / ${formatBytes(current.mem_total_bytes)}`
      : undefined
  const diskDetail =
    current?.disk_used_bytes != null && current.disk_total_bytes != null
      ? `${formatBytes(current.disk_used_bytes)} / ${formatBytes(current.disk_total_bytes)}`
      : undefined
  const netDetail =
    current?.net_rx_bytes_per_sec != null || current?.net_tx_bytes_per_sec != null
      ? `↓ ${formatBytesPerSec(current.net_rx_bytes_per_sec)} · ↑ ${formatBytesPerSec(current.net_tx_bytes_per_sec)}`
      : undefined

  return [
    {
      label: 'CPU',
      value: formatPercent(current?.cpu_percent),
      detail:
        current?.load_avg_1m != null && current.cpu_count != null
          ? `Load ${current.load_avg_1m.toFixed(2)} · ${current.cpu_count} cores`
          : current?.cpu_count != null
            ? `${current.cpu_count} cores`
            : undefined,
      accent:
        current?.cpu_percent != null && current.cpu_percent >= 85
          ? 'text-amber-300'
          : 'text-white',
    },
    {
      label: 'Memory',
      value: formatPercent(current?.mem_percent),
      detail: memDetail,
      accent:
        current?.mem_percent != null && current.mem_percent >= 85
          ? 'text-amber-300'
          : 'text-white',
    },
    {
      label: 'Disk',
      value: formatPercent(current?.disk_percent),
      detail: diskDetail,
      accent:
        current?.disk_percent != null && current.disk_percent >= 90
          ? 'text-amber-300'
          : 'text-white',
    },
    {
      label: 'Network',
      value: netDetail ? 'Live' : '—',
      detail: netDetail,
      accent: 'text-primary',
    },
    {
      label: 'Uptime',
      value: formatUptime(current?.uptime_seconds),
      detail: current?.sampled_at
        ? `Last sample ${formatDateTime(current.sampled_at)}`
        : undefined,
      accent: 'text-white',
    },
  ]
}

export interface ResourceMetricsPanelProps {
  title?: string
  emptyMessage?: string
  fetcher: () => Promise<ResourceMetricsResponse>
}

export function ResourceMetricsPanel({
  title = 'Host resources',
  emptyMessage = 'No metrics yet. Metrics appear after the agent sends its next heartbeat.',
  fetcher,
}: ResourceMetricsPanelProps) {
  const [metrics, setMetrics] = useState<ResourceMetricsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadMetrics = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!options?.silent) {
        setLoading(true)
      }
      setError(null)
      try {
        const data = await fetcher()
        setMetrics(data)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load metrics')
      } finally {
        if (!options?.silent) {
          setLoading(false)
        }
      }
    },
    [fetcher],
  )

  useEffect(() => {
    void loadMetrics()
    const timer = window.setInterval(() => {
      void loadMetrics({ silent: true })
    }, METRICS_POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [loadMetrics])

  const samples = metrics?.samples ?? []
  const current = metrics?.current ?? null
  const statCards = useMemo(() => buildStatCards(current), [current])

  const cpuSeries = useMemo(
    () => toChartPoints(samples, (sample) => sample.cpu_percent),
    [samples],
  )
  const memSeries = useMemo(
    () => toChartPoints(samples, (sample) => sample.mem_percent),
    [samples],
  )
  const diskSeries = useMemo(
    () => toChartPoints(samples, (sample) => sample.disk_percent),
    [samples],
  )
  const netRxSeries = useMemo(
    () =>
      toChartPoints(samples, (sample) =>
        sample.net_rx_bytes_per_sec != null
          ? sample.net_rx_bytes_per_sec / 1024
          : null,
      ),
    [samples],
  )
  const netTxSeries = useMemo(
    () =>
      toChartPoints(samples, (sample) =>
        sample.net_tx_bytes_per_sec != null
          ? sample.net_tx_bytes_per_sec / 1024
          : null,
      ),
    [samples],
  )

  if (loading && !metrics) {
    return <LoadingState message="Loading resource metrics…" />
  }

  if (error && !metrics) {
    return <ErrorState message={error} onRetry={() => void loadMetrics()} />
  }

  const windowHours = metrics
    ? Math.max(metrics.window_seconds / 3600, 0.1).toFixed(1)
    : '6.0'

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-white">{title}</h2>
          <p className="mt-1 text-sm text-ink-mute-2">
            Rolling {windowHours}h window · refreshed every 15s
          </p>
        </div>
        {error ? (
          <p className="text-sm text-amber-300" role="status">
            {error}
          </p>
        ) : null}
      </div>

      {!current && samples.length === 0 ? (
        <div className="rounded-md border border-hairline bg-canvas-night-soft p-6 text-sm text-ink-mute-2">
          {emptyMessage}
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            {statCards.map((card) => (
              <MetricStatCard
                key={card.label}
                label={card.label}
                value={card.value}
                detail={card.detail}
                accent={card.accent}
              />
            ))}
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <MetricAreaChart
              title="CPU usage"
              subtitle="Percent of total CPU capacity"
              data={cpuSeries}
              valueFormatter={(value) => `${value.toFixed(1)}%`}
              domain={[0, 100]}
            />
            <MetricAreaChart
              title="Memory usage"
              subtitle="Percent of RAM in use"
              data={memSeries}
              valueFormatter={(value) => `${value.toFixed(1)}%`}
              domain={[0, 100]}
            />
            <MetricAreaChart
              title="Disk usage"
              subtitle="Root filesystem utilization"
              data={diskSeries}
              valueFormatter={(value) => `${value.toFixed(1)}%`}
              domain={[0, 100]}
            />
            <MetricAreaChart
              title="Network receive"
              subtitle="Aggregate RX throughput (KiB/s)"
              data={netRxSeries}
              valueFormatter={(value) => `${value.toFixed(1)} KiB/s`}
            />
            <MetricAreaChart
              title="Network transmit"
              subtitle="Aggregate TX throughput (KiB/s)"
              data={netTxSeries}
              valueFormatter={(value) => `${value.toFixed(1)} KiB/s`}
            />
          </div>
        </>
      )}
    </div>
  )
}
