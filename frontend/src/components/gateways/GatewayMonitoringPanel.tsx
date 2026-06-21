import { Loader2, Radar, RefreshCw, Save, ShieldAlert } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button } from '../ui/Button'
import { type Column } from '../ui/DataTable'
import { ErrorState, LoadingState } from '../ui/PageState'
import { DEFAULT_PAGINATION_META } from '../ui/Pagination'
import { MonitorModuleStatusBadge, StatusBadge } from '../ui/StatusBadge'
import { MonitoringTableSection } from './MonitoringTableSection'
import { api } from '../../lib/api'
import { useDebouncedValue } from '../../hooks/useDebouncedValue'
import { formatDateTime } from '../../lib/format'
import type {
  DiscoveredHost,
  Gateway,
  GatewayMonitorPolicy,
  GatewayMonitorPolicyPatch,
  MonitorAlert,
  MonitorScanStrategy,
  PaginationMeta,
  VulnFinding,
  VulnSeverity,
} from '../../types'

const DEFAULT_MONITORED_CIDRS = '192.168.0.0/16'
const LIVE_POLL_INTERVAL_MS = 10_000
const DEFAULT_TABLE_LIMIT = 25

const filterInputClassName =
  'rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none'
const filterLabelClassName = 'flex flex-col gap-1 text-xs text-ink-mute-2'

interface MonitoringFormState {
  enabled: boolean
  monitoredCidrsText: string
  scanStrategy: MonitorScanStrategy
  chunkCount: number
  discoverIntervalMinutes: number
  vulnRescanDays: number
  vulnScanEnabled: boolean
  vulnParallelWorkers: number
  nucleiEnabled: boolean
}

interface GatewayMonitoringPanelProps {
  gateway: Gateway
  onSuccess?: (message: string) => void
  onError?: (message: string) => void
}

function policyToFormState(policy: GatewayMonitorPolicy): MonitoringFormState {
  return {
    enabled: policy.enabled,
    monitoredCidrsText: (policy.monitored_cidrs.length > 0
      ? policy.monitored_cidrs
      : [DEFAULT_MONITORED_CIDRS]
    ).join(', '),
    scanStrategy: policy.scan_strategy,
    chunkCount: policy.chunk_count,
    discoverIntervalMinutes: policy.discover_interval_minutes,
    vulnRescanDays: policy.vuln_rescan_days ?? 1,
    vulnScanEnabled: policy.vuln_scan_enabled,
    vulnParallelWorkers: policy.vuln_parallel_workers ?? 4,
    nucleiEnabled: policy.nuclei_enabled,
  }
}

function parseMonitoredCidrs(text: string): string[] {
  return text
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
}

function formatCoverageHours(hours: number | null): string {
  if (hours === null) {
    return '—'
  }
  if (hours < 24) {
    return `${hours.toFixed(1)} h`
  }
  return `${(hours / 24).toFixed(1)} d (${hours.toFixed(0)} h)`
}

const severityVariants: Record<
  VulnSeverity,
  'danger' | 'warning' | 'info' | 'neutral' | 'success'
> = {
  critical: 'danger',
  high: 'danger',
  medium: 'warning',
  low: 'info',
  info: 'neutral',
}

export function GatewayMonitoringPanel({
  gateway,
  onSuccess,
  onError,
}: GatewayMonitoringPanelProps) {
  const [policy, setPolicy] = useState<GatewayMonitorPolicy | null>(null)
  const [form, setForm] = useState<MonitoringFormState | null>(null)
  const [hosts, setHosts] = useState<DiscoveredHost[]>([])
  const [hostsMeta, setHostsMeta] = useState<PaginationMeta>(DEFAULT_PAGINATION_META)
  const [hostsPage, setHostsPage] = useState(1)
  const [hostsLimit, setHostsLimit] = useState(DEFAULT_TABLE_LIMIT)
  const [hostsIpFilter, setHostsIpFilter] = useState('')
  const [hostsIsNewFilter, setHostsIsNewFilter] = useState('')
  const [hostsVulnPendingFilter, setHostsVulnPendingFilter] = useState('')
  const [hostsLoading, setHostsLoading] = useState(false)

  const [alerts, setAlerts] = useState<MonitorAlert[]>([])
  const [alertsMeta, setAlertsMeta] = useState<PaginationMeta>(DEFAULT_PAGINATION_META)
  const [alertsPage, setAlertsPage] = useState(1)
  const [alertsLimit, setAlertsLimit] = useState(DEFAULT_TABLE_LIMIT)
  const [alertsHostIpFilter, setAlertsHostIpFilter] = useState('')
  const [alertsTypeFilter, setAlertsTypeFilter] = useState('')
  const [alertsLoading, setAlertsLoading] = useState(false)

  const [findings, setFindings] = useState<VulnFinding[]>([])
  const [findingsMeta, setFindingsMeta] = useState<PaginationMeta>(DEFAULT_PAGINATION_META)
  const [findingsPage, setFindingsPage] = useState(1)
  const [findingsLimit, setFindingsLimit] = useState(DEFAULT_TABLE_LIMIT)
  const [findingsHostIpFilter, setFindingsHostIpFilter] = useState('')
  const [findingsSeverityFilter, setFindingsSeverityFilter] = useState('')
  const [findingsSourceFilter, setFindingsSourceFilter] = useState('')
  const [findingsLoading, setFindingsLoading] = useState(false)

  const debouncedHostsIp = useDebouncedValue(hostsIpFilter)
  const debouncedAlertsHostIp = useDebouncedValue(alertsHostIpFilter)
  const debouncedFindingsHostIp = useDebouncedValue(findingsHostIpFilter)
  const debouncedFindingsSource = useDebouncedValue(findingsSourceFilter)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [ensuringModules, setEnsuringModules] = useState(false)
  const [scanningNetwork, setScanningNetwork] = useState(false)
  const [rescanningVulns, setRescanningVulns] = useState(false)
  const [scanPollActive, setScanPollActive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const loadHosts = useCallback(async () => {
    setHostsLoading(true)
    try {
      const result = await api.getGatewayMonitoringHosts(gateway.id, {
        page: hostsPage,
        limit: hostsLimit,
        ip: debouncedHostsIp,
        is_new: hostsIsNewFilter,
        vuln_scan_pending: hostsVulnPendingFilter,
      })
      setHosts(result.items)
      setHostsMeta(result.meta)
    } catch {
      // Table-level errors are non-fatal during polling.
    } finally {
      setHostsLoading(false)
    }
  }, [
    gateway.id,
    hostsPage,
    hostsLimit,
    debouncedHostsIp,
    hostsIsNewFilter,
    hostsVulnPendingFilter,
  ])

  const loadAlerts = useCallback(async () => {
    setAlertsLoading(true)
    try {
      const result = await api.getGatewayMonitoringAlerts(gateway.id, {
        page: alertsPage,
        limit: alertsLimit,
        host_ip: debouncedAlertsHostIp,
        alert_type: alertsTypeFilter,
      })
      setAlerts(result.items)
      setAlertsMeta(result.meta)
    } catch {
      // Table-level errors are non-fatal during polling.
    } finally {
      setAlertsLoading(false)
    }
  }, [
    gateway.id,
    alertsPage,
    alertsLimit,
    debouncedAlertsHostIp,
    alertsTypeFilter,
  ])

  const loadFindings = useCallback(async () => {
    setFindingsLoading(true)
    try {
      const result = await api.getGatewayMonitoringFindings(gateway.id, {
        page: findingsPage,
        limit: findingsLimit,
        host_ip: debouncedFindingsHostIp,
        severity: findingsSeverityFilter,
        source: debouncedFindingsSource,
      })
      setFindings(result.items)
      setFindingsMeta(result.meta)
    } catch {
      // Table-level errors are non-fatal during polling.
    } finally {
      setFindingsLoading(false)
    }
  }, [
    gateway.id,
    findingsPage,
    findingsLimit,
    debouncedFindingsHostIp,
    findingsSeverityFilter,
    debouncedFindingsSource,
  ])

  const loadMonitoring = useCallback(async () => {
    setError(null)
    try {
      const policyData = await api.getGatewayMonitoring(gateway.id)
      setPolicy(policyData)
      setForm(policyToFormState(policyData))
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to load monitoring data',
      )
    }
  }, [gateway.id])

  const pollLiveData = useCallback(async () => {
    await Promise.all([loadHosts(), loadAlerts(), loadFindings()])
  }, [loadAlerts, loadFindings, loadHosts])

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      setLoading(true)
      await loadMonitoring()
      if (!cancelled) {
        setLoading(false)
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [loadMonitoring])

  useEffect(() => {
    void loadHosts()
  }, [loadHosts])

  useEffect(() => {
    void loadAlerts()
  }, [loadAlerts])

  useEffect(() => {
    void loadFindings()
  }, [loadFindings])

  useEffect(() => {
    setHostsPage(1)
  }, [debouncedHostsIp, hostsIsNewFilter, hostsVulnPendingFilter])

  useEffect(() => {
    setAlertsPage(1)
  }, [debouncedAlertsHostIp, alertsTypeFilter])

  useEffect(() => {
    setFindingsPage(1)
  }, [debouncedFindingsHostIp, findingsSeverityFilter, debouncedFindingsSource])

  useEffect(() => {
    if (!policy?.vuln_scan_enabled && !scanPollActive) {
      return
    }
    const intervalId = window.setInterval(() => {
      void pollLiveData()
    }, LIVE_POLL_INTERVAL_MS)
    return () => {
      window.clearInterval(intervalId)
    }
  }, [policy?.vuln_scan_enabled, scanPollActive, pollLiveData])

  const refresh = async () => {
    setRefreshing(true)
    await loadMonitoring()
    await pollLiveData()
    setRefreshing(false)
  }

  const updateForm = <K extends keyof MonitoringFormState>(
    key: K,
    value: MonitoringFormState[K],
  ) => {
    setForm((current) => (current ? { ...current, [key]: value } : current))
    setFormError(null)
  }

  const intervalValidationError = useMemo(() => {
    if (!form || !policy) {
      return null
    }
    if (form.discoverIntervalMinutes < policy.min_interval_minutes) {
      return `Discover interval must be at least ${policy.min_interval_minutes} minutes for the current policy.`
    }
    return null
  }, [form, policy])

  const savePolicy = async () => {
    if (!form || !policy) {
      return
    }

    const monitoredCidrs = parseMonitoredCidrs(form.monitoredCidrsText)
    if (monitoredCidrs.length === 0) {
      setFormError('Enter at least one monitored CIDR.')
      return
    }
    if (form.chunkCount < 1 || form.chunkCount > 16) {
      setFormError('Chunks per cycle must be between 1 and 16.')
      return
    }
    if (form.vulnParallelWorkers < 1 || form.vulnParallelWorkers > 16) {
      setFormError('Vuln parallel workers must be between 1 and 16.')
      return
    }
    if (intervalValidationError) {
      setFormError(intervalValidationError)
      return
    }

    setSaving(true)
    setFormError(null)
    try {
      const patch: GatewayMonitorPolicyPatch = {
        enabled: form.enabled,
        monitored_cidrs: monitoredCidrs,
        scan_strategy: form.scanStrategy,
        chunk_count: form.chunkCount,
        discover_interval_minutes: form.discoverIntervalMinutes,
        vuln_rescan_days: form.vulnRescanDays,
        vuln_scan_enabled: form.vulnScanEnabled,
        vuln_parallel_workers: form.vulnParallelWorkers,
        nuclei_enabled: form.nucleiEnabled,
      }
      const updated = await api.patchGatewayMonitoring(gateway.id, patch)
      setPolicy(updated)
      setForm(policyToFormState(updated))
      onSuccess?.('Monitoring policy saved.')
    } catch (err) {
      const message =
        err instanceof Error ? err.message : 'Failed to save monitoring policy'
      setFormError(message)
      onError?.(message)
    } finally {
      setSaving(false)
    }
  }

  const ensureModules = async () => {
    setEnsuringModules(true)
    setFormError(null)
    try {
      const result = await api.ensureGatewayMonitoringModules(gateway.id)
      setPolicy(result.policy)
      setForm(policyToFormState(result.policy))
      onSuccess?.(
        result.ready
          ? 'All required monitoring modules are installed.'
          : 'Module install commands queued on gateway agent.',
      )
    } catch (err) {
      const message =
        err instanceof Error ? err.message : 'Failed to ensure monitoring modules'
      setFormError(message)
      onError?.(message)
    } finally {
      setEnsuringModules(false)
    }
  }

  const scanNetworkNow = async () => {
    if (gateway.status !== 'online') {
      setFormError('Gateway must be online to scan.')
      return
    }

    setScanningNetwork(true)
    setFormError(null)
    try {
      const result = await api.triggerGatewayMonitoringScan(gateway.id)
      const targetLabel =
        result.targets.length > 0 ? result.targets.join(', ') : 'configured subnets'
      onSuccess?.(
        `Network scan queued (${result.command_id.slice(0, 8)}…) — ${targetLabel}`,
      )
      setScanPollActive(true)
      window.setTimeout(() => {
        setScanPollActive(false)
      }, 120_000)
      const updated = await api.getGatewayMonitoring(gateway.id)
      setPolicy(updated)
      setForm(policyToFormState(updated))
      await pollLiveData()
    } catch (err) {
      const message =
        err instanceof Error ? err.message : 'Failed to trigger network scan'
      setFormError(message)
      onError?.(message)
    } finally {
      setScanningNetwork(false)
    }
  }

  const rescanVulnsNow = async () => {
    if (gateway.status !== 'online') {
      setFormError('Gateway must be online to rescan vulnerabilities.')
      return
    }
    if (!form?.vulnScanEnabled) {
      setFormError('Enable vulnerability scanning in the policy first.')
      return
    }

    setRescanningVulns(true)
    setFormError(null)
    try {
      const result = await api.triggerGatewayMonitoringVulnRescan(gateway.id)
      const hostLabel =
        result.hosts.length > 0 ? result.hosts.join(', ') : `${result.queued_count} host(s)`
      onSuccess?.(`Vuln rescan queued for ${hostLabel}`)
      setScanPollActive(true)
      window.setTimeout(() => {
        setScanPollActive(false)
      }, 300_000)
      await pollLiveData()
    } catch (err) {
      const message =
        err instanceof Error ? err.message : 'Failed to trigger vuln rescan'
      setFormError(message)
      onError?.(message)
    } finally {
      setRescanningVulns(false)
    }
  }

  const gatewayOffline = gateway.status !== 'online'
  const masscanReady =
    policy?.module_statuses.some(
      (module) => module.module_id === 'masscan' && module.status === 'installed',
    ) ?? false

  const hostsHasActiveFilters = useMemo(
    () =>
      Boolean(
        debouncedHostsIp || hostsIsNewFilter || hostsVulnPendingFilter,
      ),
    [debouncedHostsIp, hostsIsNewFilter, hostsVulnPendingFilter],
  )

  const alertsHasActiveFilters = useMemo(
    () => Boolean(debouncedAlertsHostIp || alertsTypeFilter),
    [debouncedAlertsHostIp, alertsTypeFilter],
  )

  const findingsHasActiveFilters = useMemo(
    () =>
      Boolean(
        debouncedFindingsHostIp ||
          findingsSeverityFilter ||
          debouncedFindingsSource,
      ),
    [
      debouncedFindingsHostIp,
      findingsSeverityFilter,
      debouncedFindingsSource,
    ],
  )

  const hostColumns: Column<DiscoveredHost>[] = [
    {
      key: 'ip',
      header: 'IP',
      render: (row) => (
        <span className="font-mono text-xs text-white">{row.ip}</span>
      ),
    },
    {
      key: 'hostname',
      header: 'Hostname',
      render: (row) => row.hostname || '—',
    },
    {
      key: 'mac',
      header: 'MAC',
      render: (row) =>
        row.mac ? (
          <span className="font-mono text-xs">{row.mac}</span>
        ) : (
          '—'
        ),
    },
    {
      key: 'is_new',
      header: 'Status',
      render: (row) => (
        <span className="inline-flex flex-wrap items-center gap-1.5">
          {row.is_new ? (
            <StatusBadge label="new" variant="warning" />
          ) : (
            <StatusBadge label="known" variant="neutral" />
          )}
          {row.vuln_scan_pending === true ? (
            <StatusBadge label="vuln scan pending" variant="info" />
          ) : null}
        </span>
      ),
    },
    {
      key: 'last_seen_at',
      header: 'Last seen',
      render: (row) => formatDateTime(row.last_seen_at),
    },
    {
      key: 'last_vuln_scan_at',
      header: 'Last vuln scan',
      render: (row) => formatDateTime(row.last_vuln_scan_at),
    },
  ]

  const alertColumns: Column<MonitorAlert>[] = [
    {
      key: 'alert_type',
      header: 'Type',
      render: (row) => (
        <span className="capitalize">{row.alert_type.replace(/_/g, ' ')}</span>
      ),
    },
    {
      key: 'host_ip',
      header: 'Host',
      render: (row) => (
        <span className="font-mono text-xs">{row.host_ip}</span>
      ),
    },
    {
      key: 'message',
      header: 'Message',
      render: (row) => row.message || '—',
    },
    {
      key: 'created_at',
      header: 'Created',
      render: (row) => formatDateTime(row.created_at),
    },
  ]

  const findingColumns: Column<VulnFinding>[] = [
    {
      key: 'severity',
      header: 'Severity',
      render: (row) => (
        <StatusBadge
          label={row.severity}
          variant={severityVariants[row.severity]}
        />
      ),
    },
    {
      key: 'host_ip',
      header: 'Host',
      render: (row) => (
        <span className="font-mono text-xs">{row.host_ip}</span>
      ),
    },
    {
      key: 'title',
      header: 'Finding',
      render: (row) => row.title,
    },
    {
      key: 'source',
      header: 'Source',
      render: (row) => row.source,
    },
    {
      key: 'found_at',
      header: 'Found',
      render: (row) => formatDateTime(row.found_at),
    },
  ]

  if (loading) {
    return <LoadingState message="Loading monitoring…" />
  }

  if (error || !policy || !form) {
    return (
      <ErrorState
        message={error ?? 'Monitoring policy unavailable'}
        onRetry={() => void refresh()}
      />
    )
  }

  const chunksDisabled = form.scanStrategy === 'full_sweep'

  return (
    <div className="space-y-6">
      <section className="space-y-4 rounded-md border border-hairline bg-canvas-night-soft p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-medium text-white">Monitoring policy</h3>
            <p className="text-xs text-ink-mute-2">
              Scheduled discovery scans and optional vulnerability checks on
              gateway LAN targets.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={
                scanningNetwork ||
                rescanningVulns ||
                gatewayOffline ||
                !masscanReady ||
                saving ||
                ensuringModules
              }
              onClick={() => void scanNetworkNow()}
            >
              {scanningNetwork ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Radar className="h-4 w-4" aria-hidden />
              )}
              Scan network
            </Button>
            <Button
              variant="secondary"
              disabled={
                rescanningVulns ||
                scanningNetwork ||
                gatewayOffline ||
                !form?.vulnScanEnabled ||
                saving ||
                ensuringModules
              }
              onClick={() => void rescanVulnsNow()}
            >
              {rescanningVulns ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <ShieldAlert className="h-4 w-4" aria-hidden />
              )}
              Rescan vulnerabilities
            </Button>
            <Button
              variant="secondary"
              disabled={refreshing || saving || ensuringModules || scanningNetwork || rescanningVulns}
              onClick={() => void refresh()}
            >
              {refreshing ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <RefreshCw className="h-4 w-4" aria-hidden />
              )}
              Refresh
            </Button>
            <Button
              disabled={saving || ensuringModules || scanningNetwork || rescanningVulns || Boolean(intervalValidationError)}
              onClick={() => void savePolicy()}
            >
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Save className="h-4 w-4" aria-hidden />
              )}
              Save policy
            </Button>
          </div>
        </div>

        {formError ? (
          <p
            role="alert"
            className="rounded-sm border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200"
          >
            {formError}
          </p>
        ) : null}

        <div className="grid gap-4 md:grid-cols-2">
          <label className="flex cursor-pointer items-center gap-3 text-sm text-white">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(event) => updateForm('enabled', event.target.checked)}
              className="h-4 w-4 rounded-sm border-hairline-strong bg-canvas-night accent-primary"
            />
            Monitoring enabled
          </label>

          <div className="rounded-sm border border-hairline bg-canvas-night px-3 py-2 text-sm">
            <p className="text-xs text-ink-mute-2">Last scheduled</p>
            <p className="text-white">
              {formatDateTime(policy.last_scheduled_at)}
            </p>
          </div>
        </div>

        <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
          Monitored CIDRs
          <input
            type="text"
            value={form.monitoredCidrsText}
            onChange={(event) =>
              updateForm('monitoredCidrsText', event.target.value)
            }
            className="rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 font-mono text-sm text-white focus:border-primary focus:outline-none"
            placeholder={DEFAULT_MONITORED_CIDRS}
          />
          <span>Comma-separated networks to scan (default 192.168.0.0/16).</span>
        </label>

        <div className="grid gap-4 md:grid-cols-2">
          <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
            Scan strategy
            <select
              value={form.scanStrategy}
              onChange={(event) =>
                updateForm(
                  'scanStrategy',
                  event.target.value as MonitorScanStrategy,
                )
              }
              className="cursor-pointer rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none"
            >
              <option value="rotating_chunks">Rotating chunks</option>
              <option value="full_sweep">Full sweep</option>
            </select>
          </label>

          <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
            Chunks per cycle
            <input
              type="number"
              min={1}
              max={16}
              value={form.chunkCount}
              disabled={chunksDisabled}
              onChange={(event) =>
                updateForm('chunkCount', Number(event.target.value))
              }
              className="rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
            />
            <span>
              {chunksDisabled
                ? 'Not used for full sweep — every /24 chunk runs each cycle.'
                : 'Number of /24 chunks scanned per cycle (1–16).'}
            </span>
          </label>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
            Discover interval (minutes)
            <input
              type="number"
              min={policy.min_interval_minutes}
              max={10080}
              value={form.discoverIntervalMinutes}
              onChange={(event) =>
                updateForm(
                  'discoverIntervalMinutes',
                  Number(event.target.value),
                )
              }
              className="rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none"
            />
            {intervalValidationError ? (
              <span className="text-amber-300">{intervalValidationError}</span>
            ) : (
              <span>Minimum {policy.min_interval_minutes} min for current policy.</span>
            )}
          </label>

          <div className="rounded-sm border border-hairline bg-canvas-night px-3 py-2 text-sm">
            <p className="text-xs text-ink-mute-2">Min interval (read-only)</p>
            <p className="font-medium text-white">
              {policy.min_interval_minutes} min
            </p>
          </div>

          <div className="rounded-sm border border-hairline bg-canvas-night px-3 py-2 text-sm">
            <p className="text-xs text-ink-mute-2">Full coverage (read-only)</p>
            <p className="font-medium text-white">
              {formatCoverageHours(policy.full_coverage_hours)}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-6">
          <label className="flex cursor-pointer items-center gap-3 text-sm text-white">
            <input
              type="checkbox"
              checked={form.vulnScanEnabled}
              onChange={(event) =>
                updateForm('vulnScanEnabled', event.target.checked)
              }
              className="h-4 w-4 rounded-sm border-hairline-strong bg-canvas-night accent-primary"
            />
            Vulnerability scan enabled
          </label>

          <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
            Vuln rescan interval (days)
            <input
              type="number"
              min={1}
              max={90}
              value={form.vulnRescanDays}
              disabled={!form.vulnScanEnabled}
              onChange={(event) =>
                updateForm('vulnRescanDays', Number(event.target.value))
              }
              className="w-24 rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
            />
            <span>Re-scan hosts after this many days (default 1).</span>
          </label>

          <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
            Vuln parallel workers
            <input
              type="number"
              min={1}
              max={16}
              value={form.vulnParallelWorkers}
              disabled={!form.vulnScanEnabled}
              onChange={(event) =>
                updateForm('vulnParallelWorkers', Number(event.target.value))
              }
              className="w-24 rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
            />
            <span>Concurrent vuln scan workers (1–16).</span>
          </label>

          <label className="flex cursor-pointer items-center gap-3 text-sm text-white">
            <input
              type="checkbox"
              checked={form.nucleiEnabled}
              disabled={!form.vulnScanEnabled}
              onChange={(event) =>
                updateForm('nucleiEnabled', event.target.checked)
              }
              className="h-4 w-4 rounded-sm border-hairline-strong bg-canvas-night accent-primary disabled:cursor-not-allowed disabled:opacity-50"
            />
            Nuclei enabled
          </label>
        </div>
      </section>

      <section className="space-y-3 rounded-md border border-hairline bg-canvas-night-soft p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-medium text-white">Required modules</h3>
            <p className="text-xs text-ink-mute-2">
              Masscan for discovery; additional modules when vuln scanning is on.
            </p>
          </div>
          <Button
            variant="secondary"
            disabled={ensuringModules || saving || !gateway.agent_id}
            onClick={() => void ensureModules()}
          >
            {ensuringModules ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <ShieldAlert className="h-4 w-4" aria-hidden />
            )}
            Install all modules
          </Button>
        </div>
        <div className="flex flex-wrap gap-2">
          {policy.module_statuses.map((entry) => (
            <MonitorModuleStatusBadge
              key={entry.module_id}
              moduleId={entry.module_id}
              status={entry.status}
            />
          ))}
        </div>
        {!gateway.agent_id ? (
          <p className="text-xs text-amber-300/80">
            Gateway agent must be enrolled before modules can be installed.
          </p>
        ) : null}
      </section>

      <MonitoringTableSection
        title="Discovered hosts"
        description="Hosts seen during scheduled monitor scans"
        columns={hostColumns}
        rows={hosts}
        rowKey={(row) => row.id}
        emptyMessage="No hosts discovered yet — enable monitoring and wait for the next scan cycle."
        meta={hostsMeta}
        onPageChange={setHostsPage}
        onLimitChange={(limit) => {
          setHostsLimit(limit)
          setHostsPage(1)
        }}
        loading={hostsLoading}
        hasActiveFilters={hostsHasActiveFilters}
        filters={
          <>
            <label className={filterLabelClassName}>
              IP contains
              <input
                type="text"
                value={hostsIpFilter}
                onChange={(event) => setHostsIpFilter(event.target.value)}
                placeholder="192.168.103"
                className={`${filterInputClassName} font-mono`}
              />
            </label>
            <label className={filterLabelClassName}>
              Host status
              <select
                value={hostsIsNewFilter}
                onChange={(event) => setHostsIsNewFilter(event.target.value)}
                className={filterInputClassName}
              >
                <option value="">All hosts</option>
                <option value="true">New only</option>
                <option value="false">Known only</option>
              </select>
            </label>
            <label className={filterLabelClassName}>
              Vuln queue
              <select
                value={hostsVulnPendingFilter}
                onChange={(event) => setHostsVulnPendingFilter(event.target.value)}
                className={filterInputClassName}
              >
                <option value="">Any</option>
                <option value="true">Pending scan</option>
                <option value="false">Not pending</option>
              </select>
            </label>
          </>
        }
      />

      <MonitoringTableSection
        title="Alerts"
        description="Recent monitoring events"
        columns={alertColumns}
        rows={alerts}
        rowKey={(row) => row.id}
        emptyMessage="No monitoring alerts yet."
        meta={alertsMeta}
        onPageChange={setAlertsPage}
        onLimitChange={(limit) => {
          setAlertsLimit(limit)
          setAlertsPage(1)
        }}
        loading={alertsLoading}
        hasActiveFilters={alertsHasActiveFilters}
        filters={
          <>
            <label className={filterLabelClassName}>
              Host IP contains
              <input
                type="text"
                value={alertsHostIpFilter}
                onChange={(event) => setAlertsHostIpFilter(event.target.value)}
                placeholder="192.168.103.101"
                className={`${filterInputClassName} font-mono`}
              />
            </label>
            <label className={filterLabelClassName}>
              Alert type
              <select
                value={alertsTypeFilter}
                onChange={(event) => setAlertsTypeFilter(event.target.value)}
                className={filterInputClassName}
              >
                <option value="">All types</option>
                <option value="new_host">New host</option>
              </select>
            </label>
          </>
        }
      />

      <MonitoringTableSection
        title="Vulnerability findings"
        description="Latest findings from vuln scans (when enabled)"
        columns={findingColumns}
        rows={findings}
        rowKey={(row) => row.id}
        emptyMessage="No vulnerability findings yet."
        meta={findingsMeta}
        onPageChange={setFindingsPage}
        onLimitChange={(limit) => {
          setFindingsLimit(limit)
          setFindingsPage(1)
        }}
        loading={findingsLoading}
        hasActiveFilters={findingsHasActiveFilters}
        filters={
          <>
            <label className={filterLabelClassName}>
              Host IP contains
              <input
                type="text"
                value={findingsHostIpFilter}
                onChange={(event) => setFindingsHostIpFilter(event.target.value)}
                placeholder="192.168.103.101"
                className={`${filterInputClassName} font-mono`}
              />
            </label>
            <label className={filterLabelClassName}>
              Severity
              <select
                value={findingsSeverityFilter}
                onChange={(event) => setFindingsSeverityFilter(event.target.value)}
                className={filterInputClassName}
              >
                <option value="">All severities</option>
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
                <option value="info">Info</option>
              </select>
            </label>
            <label className={filterLabelClassName}>
              Source contains
              <input
                type="text"
                value={findingsSourceFilter}
                onChange={(event) => setFindingsSourceFilter(event.target.value)}
                placeholder="nuclei"
                className={filterInputClassName}
              />
            </label>
          </>
        }
      />
    </div>
  )
}
