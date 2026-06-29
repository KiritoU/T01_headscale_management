import { ArrowLeft, Copy, Loader2, Radar, RefreshCw, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { GatewayMonitoringPanel } from '../components/gateways/GatewayMonitoringPanel'
import { ResourceMetricsPanel } from '../components/metrics/ResourceMetricsPanel'
import { TailscaleConnectPanel } from '../components/gateways/TailscaleConnectPanel'
import { Button } from '../components/ui/Button'
import { DataTable, type Column } from '../components/ui/DataTable'
import { ErrorState, LoadingState } from '../components/ui/PageState'
import {
  GatewayStatusBadge,
  ModuleBadge,
  OnlineIndicator,
} from '../components/ui/StatusBadge'
import { api } from '../lib/api'
import { copyToClipboard } from '../lib/clipboard'
import { formatDateTime } from '../lib/format'
import {
  mergeScanSummaries,
  parseScanResult,
  resolveScanMode,
  scanSubnetRowKey,
  type ScanMode,
} from '../lib/gatewayScan'
import type {
  Gateway,
  GatewayCommandDetail,
  GatewayRoute,
  GatewayStatus,
  ScanSubnet,
  ScanSummary,
} from '../types'

const KNOWN_MODULES = ['tailscale', 'nmap', 'masscan'] as const
const SCAN_POLL_INTERVAL_MS = 2000
const SCAN_PAGE_SIZE = 10
/** UI stops polling after this; agent may still run until its own nmap timeout. */
const SCAN_POLL_MAX_MS = 2 * 60 * 60 * 1000
const SCAN_POLL_MAX_HOURS = SCAN_POLL_MAX_MS / (60 * 60 * 1000)

type GatewayDetailTab = 'overview' | 'monitoring' | 'resources'

const GATEWAY_DETAIL_TABS: { id: GatewayDetailTab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'resources', label: 'Resources' },
  { id: 'monitoring', label: 'Monitoring' },
]

function isGatewayOnline(gateway: Gateway): boolean {
  return gateway.status === 'online'
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

function findInflightScan(
  gateway: Gateway,
): { command: GatewayCommandDetail; mode: ScanMode } | null {
  const candidates: { command: GatewayCommandDetail; mode: ScanMode }[] = []
  if (gateway.last_discover_scan) {
    candidates.push({ command: gateway.last_discover_scan, mode: 'discover' })
  }
  if (gateway.last_target_scan) {
    candidates.push({ command: gateway.last_target_scan, mode: 'target' })
  }
  const inflight = candidates
    .filter(
      ({ command }) =>
        command.state === 'pending' || command.state === 'dispatched',
    )
    .sort(
      (left, right) =>
        Date.parse(right.command.created_at) -
        Date.parse(left.command.created_at),
    )
  return inflight[0] ?? null
}

export function GatewayDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [gateway, setGateway] = useState<Gateway | null>(null)
  const [routes, setRoutes] = useState<GatewayRoute[]>([])
  const [discoverSubnets, setDiscoverSubnets] = useState<ScanSubnet[]>([])
  const [targetSubnets, setTargetSubnets] = useState<ScanSubnet[]>([])
  const [discoverSummary, setDiscoverSummary] = useState<ScanSummary | null>(null)
  const [targetSummary, setTargetSummary] = useState<ScanSummary | null>(null)
  const [scanNmapAvailable, setScanNmapAvailable] = useState<boolean | null>(
    null,
  )
  const [activeScanCommandId, setActiveScanCommandId] = useState<string | null>(
    null,
  )
  const [activeScanMode, setActiveScanMode] = useState<ScanMode | null>(null)
  const [scanPolling, setScanPolling] = useState(false)
  const [scanMode, setScanMode] = useState<ScanMode>('discover')
  const [targetCidr, setTargetCidr] = useState('192.168.102.0/24')
  const [scanPage, setScanPage] = useState(1)
  const [expandedSubnet, setExpandedSubnet] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [installingModule, setInstallingModule] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)
  const [copyingCurl, setCopyingCurl] = useState(false)
  const [routesLoading, setRoutesLoading] = useState(false)
  const [routesError, setRoutesError] = useState<string | null>(null)
  const [scanRefreshKey, setScanRefreshKey] = useState(0)
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [activeTab, setActiveTab] = useState<GatewayDetailTab>('overview')

  const loadGateway = useCallback(async () => {
    if (!id) {
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await api.getGateway(id)
      setGateway(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load gateway')
    } finally {
      setLoading(false)
    }
  }, [id])

  const fetchGatewayMetrics = useCallback(() => {
    if (!id) {
      return Promise.reject(new Error('Gateway not found'))
    }
    return api.getGatewayMetrics(id)
  }, [id])

  const loadRoutes = useCallback(async () => {
    if (!id) {
      return
    }
    setRoutesLoading(true)
    setRoutesError(null)
    try {
      const data = await api.getGatewayRoutes(id)
      setRoutes(data)
    } catch (err) {
      setRoutesError(
        err instanceof Error ? err.message : 'Failed to load gateway routes',
      )
      setRoutes([])
    } finally {
      setRoutesLoading(false)
    }
  }, [id])

  const applyScanResultForMode = useCallback(
    (mode: ScanMode, command: GatewayCommandDetail) => {
      const parsed = parseScanResult(command)
      const resolvedMode = resolveScanMode(command, parsed)

      if (resolvedMode === 'target') {
        setTargetSubnets(parsed.subnets)
        setTargetSummary(parsed.summary)
      } else {
        setDiscoverSubnets(parsed.subnets)
        setDiscoverSummary(parsed.summary)
      }

      if (parsed.nmapAvailable !== null) {
        setScanNmapAvailable(parsed.nmapAvailable)
      }

      setScanPage(1)
      setExpandedSubnet(null)

      const hostCount = parsed.summary?.total_hosts ?? 0
      const label = mode === 'target' ? 'Target CIDR scan' : 'Discover local scan'
      if (parsed.subnets.length === 0) {
        setActionMessage(`${label} complete — no subnets in result.`)
      } else if (hostCount === 0) {
        setActionMessage(
          `${label} complete — ${parsed.subnets[0]?.cidr ?? 'target'} scanned; no live hosts responded.`,
        )
      } else {
        setActionMessage(
          `${label} complete — ${parsed.subnets.length} subnet${parsed.subnets.length === 1 ? '' : 's'}, ${hostCount} live host${hostCount === 1 ? '' : 's'}.`,
        )
      }
    },
    [],
  )

  const hydrateScanFromCommand = useCallback(
    (command: GatewayCommandDetail) => {
      const mode = resolveScanMode(command, parseScanResult(command))
      if (command.state === 'acked') {
        applyScanResultForMode(mode, command)
      }
    },
    [applyScanResultForMode],
  )

  const allScanSubnets = useMemo(
    () => [...discoverSubnets, ...targetSubnets],
    [discoverSubnets, targetSubnets],
  )

  const combinedScanSummary = useMemo(
    () => mergeScanSummaries(discoverSummary, targetSummary),
    [discoverSummary, targetSummary],
  )

  const scanPageCount = Math.max(1, Math.ceil(allScanSubnets.length / SCAN_PAGE_SIZE))

  const paginatedScanSubnets = useMemo(() => {
    const start = (scanPage - 1) * SCAN_PAGE_SIZE
    return allScanSubnets.slice(start, start + SCAN_PAGE_SIZE)
  }, [allScanSubnets, scanPage])

  useEffect(() => {
    if (scanPage > scanPageCount) {
      setScanPage(scanPageCount)
    }
  }, [scanPage, scanPageCount])

  useEffect(() => {
    if (!id || !activeScanCommandId || !scanPolling || !activeScanMode) {
      return
    }

    let cancelled = false
    const deadline = Date.now() + SCAN_POLL_MAX_MS
    const pollingMode = activeScanMode

    const pollUntilDone = async () => {
      while (!cancelled) {
        if (Date.now() >= deadline) {
          setActionError(
            `Scan still running on gateway after ${SCAN_POLL_MAX_HOURS}h — refresh this page later to fetch results.`,
          )
          setScanPolling(false)
          setActiveScanMode(null)
          return
        }

        await sleep(SCAN_POLL_INTERVAL_MS)
        try {
          const command = await api.getGatewayCommand(id, activeScanCommandId)
          if (cancelled) {
            return
          }

          if (command.state === 'failed') {
            const logs =
              command.result?.logs ?? 'Network scan failed on gateway agent.'
            setActionError(
              typeof logs === 'string'
                ? logs
                : 'Network scan failed on gateway agent.',
            )
            setScanPolling(false)
            setActiveScanMode(null)
            return
          }

          if (command.state === 'acked') {
            applyScanResultForMode(pollingMode, command)
            setScanRefreshKey((current) => current + 1)
            setScanPolling(false)
            setActiveScanMode(null)
            return
          }
        } catch (err) {
          if (!cancelled) {
            setActionError(
              err instanceof Error ? err.message : 'Failed to poll scan command',
            )
            setScanPolling(false)
            setActiveScanMode(null)
          }
          return
        }
      }
    }

    void pollUntilDone()

    return () => {
      cancelled = true
    }
  }, [
    activeScanCommandId,
    activeScanMode,
    applyScanResultForMode,
    id,
    scanPolling,
  ])

  useEffect(() => {
    void loadGateway()
    void loadRoutes()
  }, [loadGateway, loadRoutes])

  useEffect(() => {
    if (!gateway) {
      return
    }

    if (gateway.last_discover_scan) {
      hydrateScanFromCommand(gateway.last_discover_scan)
    }
    if (gateway.last_target_scan) {
      hydrateScanFromCommand(gateway.last_target_scan)
    }

    const inflight = findInflightScan(gateway)
    if (inflight) {
      setActiveScanCommandId(inflight.command.id)
      setActiveScanMode(inflight.mode)
      setScanPolling(true)
      setActionMessage(
        `${inflight.mode === 'target' ? 'Target CIDR' : 'Discover local'} scan in progress (${inflight.command.id.slice(0, 8)}…)…`,
      )
    }
  }, [gateway, hydrateScanFromCommand])

  const runCommand = async (
    label: string,
    command: string,
    payload: Record<string, unknown> = {},
    onSuccess?: () => void,
  ) => {
    if (!id) {
      return
    }
    setActionError(null)
    setActionMessage(null)
    try {
      const result = await api.sendGatewayCommand(id, { command, payload })
      setActionMessage(
        `${label} command queued (${result.id.slice(0, 8)}…, state: ${result.state})`,
      )
      await loadGateway()
      onSuccess?.()
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : `Failed to dispatch ${label}`,
      )
    }
  }

  const installModule = async (moduleName: string) => {
    setInstallingModule(moduleName)
    await runCommand(`Install ${moduleName}`, 'install_module', { module: moduleName })
    setInstallingModule(null)
  }

  const scanNetwork = async () => {
    if (!id) {
      return
    }
    if (scanMode === 'target' && !targetCidr.trim()) {
      setActionError('Enter a CIDR to scan (e.g. 192.168.0.0/24).')
      return
    }
    setScanning(true)
    setActionError(null)
    setActionMessage(null)
    setExpandedSubnet(null)
    try {
      const payload =
        scanMode === 'target'
          ? { mode: 'target', targets: [targetCidr.trim()] }
          : { mode: 'discover' }
      const result = await api.sendGatewayCommand(id, {
        command: 'scan_network',
        payload,
      })
      setActiveScanCommandId(result.id)
      setActiveScanMode(scanMode)
      setScanPolling(true)
      setActionMessage(
        `${scanMode === 'target' ? 'Target CIDR' : 'Discover local'} scan queued (${result.id.slice(0, 8)}…) — agent will report results when finished.`,
      )
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to scan network')
    } finally {
      setScanning(false)
    }
  }

  const deleteGateway = async () => {
    if (!id) {
      return
    }
    setDeleting(true)
    setActionError(null)
    setActionMessage(null)
    try {
      await api.deleteGateway(id)
      navigate('/gateways')
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : 'Failed to delete gateway',
      )
      setDeleteConfirmOpen(false)
    } finally {
      setDeleting(false)
    }
  }

  const copyEnrollmentCurl = async () => {
    if (!gateway) {
      return
    }
    setCopyingCurl(true)
    setActionError(null)
    setActionMessage(null)
    try {
      const tokenResult = await api.createEnrollmentToken(gateway.tenant_id)
      await copyToClipboard(tokenResult.install_command)
      setActionMessage('Enrollment curl command copied to clipboard.')
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : 'Failed to copy enrollment curl',
      )
    } finally {
      setCopyingCurl(false)
    }
  }

  const hasTailscale = gateway?.installed_modules.includes('tailscale') ?? false
  const hasNmap = gateway?.installed_modules.includes('nmap') ?? false

  const scanColumns: Column<ScanSubnet>[] = [
    {
      key: 'scan_mode',
      header: 'Scan',
      render: (row) =>
        row.scan_mode === 'target' ? (
          <span className="rounded-sm bg-violet-500/15 px-2 py-0.5 text-xs text-violet-200">
            Target CIDR
          </span>
        ) : (
          <span className="rounded-sm bg-sky-500/15 px-2 py-0.5 text-xs text-sky-200">
            Discover
          </span>
        ),
    },
    {
      key: 'cidr',
      header: 'CIDR',
      render: (row) => (
        <span className="font-mono text-xs text-white">{row.cidr}</span>
      ),
    },
    {
      key: 'network',
      header: 'Network',
      render: (row) =>
        row.is_local ? (
          <span className="rounded-sm bg-primary/15 px-2 py-0.5 text-xs text-primary">
            Gateway LAN
          </span>
        ) : (
          <span className="rounded-sm bg-amber-500/15 px-2 py-0.5 text-xs text-amber-200">
            Remote / target
          </span>
        ),
    },
    {
      key: 'interface',
      header: 'Interface',
      render: (row) => row.interface || '—',
    },
    {
      key: 'source',
      header: 'Source',
      render: (row) => row.source,
    },
    {
      key: 'live_hosts',
      header: 'Live hosts',
      render: (row) => {
        const rowKey = scanSubnetRowKey(row)
        return row.live_hosts === null ? (
          <span className="text-ink-mute-2">—</span>
        ) : (
          <button
            type="button"
            className="cursor-pointer text-white hover:text-primary"
            disabled={!row.hosts?.length}
            onClick={() =>
              setExpandedSubnet((current) =>
                current === rowKey ? null : rowKey,
              )
            }
          >
            {row.live_hosts}
            {row.hosts?.length ? ' ▾' : ''}
          </button>
        )
      },
    },
  ]

  const routeColumns: Column<GatewayRoute>[] = [
    {
      key: 'cidr',
      header: 'CIDR',
      render: (row) => <span className="font-mono text-xs">{row.cidr}</span>,
    },
    {
      key: 'approved',
      header: 'Approved',
      render: (row) => (row.approved ? 'yes' : 'no'),
    },
    {
      key: 'enabled',
      header: 'Enabled',
      render: (row) => (row.enabled ? 'yes' : 'no'),
    },
  ]

  if (!id) {
    return <ErrorState message="Gateway ID is missing." />
  }

  if (loading) {
    return <LoadingState message="Loading gateway…" />
  }

  if (error || !gateway) {
    return (
      <div className="space-y-4">
        <Link
          to="/gateways"
          className="inline-flex cursor-pointer items-center gap-2 text-sm text-ink-mute-2 hover:text-primary"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
          Back to gateways
        </Link>
        <ErrorState
          message={error ?? 'Gateway not found'}
          onRetry={() => void loadGateway()}
        />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <Link
            to="/gateways"
            className="inline-flex cursor-pointer items-center gap-2 text-sm text-ink-mute-2 hover:text-primary"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden />
            Back to gateways
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-lg font-semibold text-white">
              {gateway.hostname || 'Unnamed gateway'}
            </h2>
            <GatewayStatusBadge status={gateway.status as GatewayStatus} />
            <OnlineIndicator online={isGatewayOnline(gateway)} />
          </div>
          <p className="font-mono text-xs text-ink-mute-2">{gateway.id}</p>
          <p className="text-sm text-ink-mute-2">
            Tenant:{' '}
            <Link
              to={`/tenants/${gateway.tenant_id}`}
              className="cursor-pointer font-mono text-primary hover:text-primary-soft"
            >
              {gateway.tenant_slug}
            </Link>
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            disabled={copyingCurl}
            onClick={() => void copyEnrollmentCurl()}
          >
            {copyingCurl ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Copy className="h-4 w-4" aria-hidden />
            )}
            Copy enrollment curl
          </Button>
          <Button variant="secondary" onClick={() => void loadGateway()}>
            <RefreshCw className="h-4 w-4" aria-hidden />
            Refresh
          </Button>
          <Button
            variant="secondary"
            className="text-red-200 hover:border-red-500/40 hover:bg-red-500/10"
            onClick={() => setDeleteConfirmOpen(true)}
          >
            <Trash2 className="h-4 w-4" aria-hidden />
            Delete
          </Button>
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

      <div
        className="flex flex-wrap gap-2 border-b border-hairline pb-1"
        role="tablist"
        aria-label="Gateway sections"
      >
        {GATEWAY_DETAIL_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            className={`cursor-pointer rounded-sm px-3 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'bg-primary/15 text-primary'
                : 'text-ink-mute-2 hover:bg-white/5 hover:text-white'
            }`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'monitoring' ? (
        <GatewayMonitoringPanel
          gateway={gateway}
          onSuccess={(message) => {
            setActionError(null)
            setActionMessage(message)
          }}
          onError={(message) => {
            setActionMessage(null)
            setActionError(message)
          }}
        />
      ) : null}

      {activeTab === 'resources' ? (
        <ResourceMetricsPanel
          title={`${gateway.hostname || gateway.tenant_slug} resources`}
          fetcher={fetchGatewayMetrics}
          emptyMessage={
            gateway.status === 'pending'
              ? 'Gateway has not enrolled yet. Metrics appear after the agent connects.'
              : 'No metrics yet. Metrics appear after the gateway agent sends its next heartbeat.'
          }
        />
      ) : null}

      {activeTab === 'overview' ? (
        <>
      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-md border border-hairline bg-canvas-night-soft p-4">
          <h3 className="mb-3 text-sm font-medium text-ink-mute-2">Details</h3>
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-ink-mute-2">Agent</dt>
              <dd className="font-mono text-xs text-white">
                {gateway.agent_id ?? '—'}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink-mute-2">Tailscale node</dt>
              <dd className="font-mono text-xs text-white">
                {gateway.tailscale_node_id || '—'}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink-mute-2">Last heartbeat</dt>
              <dd className="text-white">
                {formatDateTime(gateway.last_heartbeat_at)}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink-mute-2">Tags</dt>
              <dd className="text-right text-white">
                {gateway.custom_tags.length > 0
                  ? gateway.custom_tags.join(', ')
                  : '—'}
              </dd>
            </div>
          </dl>
        </div>

        <div className="rounded-md border border-hairline bg-canvas-night-soft p-4">
          <h3 className="mb-3 text-sm font-medium text-ink-mute-2">Modules</h3>
          <div className="mb-4 flex flex-wrap gap-2">
            {gateway.installed_modules
              .filter((name) => KNOWN_MODULES.includes(name as (typeof KNOWN_MODULES)[number]))
              .map((moduleName) => (
                <ModuleBadge key={moduleName} moduleName={moduleName} />
              ))}
            {gateway.installed_modules.filter((name) =>
              KNOWN_MODULES.includes(name as (typeof KNOWN_MODULES)[number]),
            ).length === 0 ? (
              <span className="text-sm text-ink-mute-2">No optional modules installed</span>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              disabled={hasTailscale || installingModule !== null}
              onClick={() => void installModule('tailscale')}
            >
              {installingModule === 'tailscale' ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : null}
              Cài Tailscale
            </Button>
            <Button
              variant="secondary"
              disabled={hasNmap || installingModule !== null}
              onClick={() => void installModule('nmap')}
            >
              {installingModule === 'nmap' ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : null}
              Cài Nmap
            </Button>
          </div>
        </div>
      </section>

      <section className="space-y-3 rounded-md border border-hairline bg-canvas-night-soft p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-medium text-white">Network scan</h3>
            <p className="text-xs text-ink-mute-2">
              Discover local subnets from the gateway, or scan a specific CIDR
              (requires Nmap module).
            </p>
          </div>
          <Button
            variant="secondary"
            disabled={scanning || scanPolling || !gateway.agent_id}
            onClick={() => void scanNetwork()}
          >
            {scanning || scanPolling ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Radar className="h-4 w-4" aria-hidden />
            )}
            {scanMode === 'target' ? 'Scan CIDR' : 'Discover subnets'}
          </Button>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            variant={scanMode === 'discover' ? 'primary' : 'secondary'}
            onClick={() => setScanMode('discover')}
          >
            Discover local
          </Button>
          <Button
            variant={scanMode === 'target' ? 'primary' : 'secondary'}
            disabled={!hasNmap}
            onClick={() => setScanMode('target')}
          >
            Scan CIDR
          </Button>
        </div>

        {scanMode === 'target' ? (
          <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
            Target CIDR
            <input
              type="text"
              value={targetCidr}
              onChange={(event) => setTargetCidr(event.target.value)}
              className="rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 font-mono text-sm text-white focus:border-primary focus:outline-none"
              placeholder="192.168.0.0/24"
            />
            <span className="text-ink-mute-2">
              Gateway scans this network from its perspective. Use the exact
              subnet of your hosts — e.g. 192.168.102.0/24 for 192.168.102.x,
              not 192.168.0.0/24.
            </span>
          </label>
        ) : null}

        {combinedScanSummary ? (
          <div className="grid gap-3 text-sm md:grid-cols-4">
            <div className="rounded-sm border border-hairline bg-canvas-night px-3 py-2">
              <p className="text-xs text-ink-mute-2">Subnets</p>
              <p className="font-medium text-white">
                {combinedScanSummary.subnet_count}
              </p>
            </div>
            <div className="rounded-sm border border-hairline bg-canvas-night px-3 py-2">
              <p className="text-xs text-ink-mute-2">Live hosts</p>
              <p className="font-medium text-white">
                {combinedScanSummary.total_hosts}
              </p>
            </div>
            <div className="rounded-sm border border-hairline bg-canvas-night px-3 py-2">
              <p className="text-xs text-ink-mute-2">Gateway LAN</p>
              <p className="font-medium text-white">
                {combinedScanSummary.local_networks}
              </p>
            </div>
            <div className="rounded-sm border border-hairline bg-canvas-night px-3 py-2">
              <p className="text-xs text-ink-mute-2">Remote targets</p>
              <p className="font-medium text-white">
                {combinedScanSummary.target_networks}
              </p>
            </div>
          </div>
        ) : null}

        {activeScanCommandId ? (
          <p className="text-xs text-ink-mute-2">
            Scan command:{' '}
            <span className="font-mono">{activeScanCommandId}</span>
            {scanPolling
              ? ' — running on gateway agent; results appear when the agent acks.'
              : null}
          </p>
        ) : null}
        {scanNmapAvailable === false ? (
          <p className="text-xs text-amber-300/80">
            Nmap not available for this scan — live host counts were not
            enriched.
          </p>
        ) : null}
        {!hasNmap && scanMode === 'target' ? (
          <p className="text-xs text-amber-300/80">
            Install the Nmap module before scanning a custom CIDR.
          </p>
        ) : null}
        {!hasNmap && scanMode === 'discover' && scanNmapAvailable === null ? (
          <p className="text-xs text-amber-300/80">
            Nmap module not installed — live host enrichment unavailable on
            discover scans.
          </p>
        ) : null}
        <DataTable
          columns={scanColumns}
          rows={paginatedScanSubnets}
          rowKey={scanSubnetRowKey}
          emptyMessage={
            scanPolling
              ? 'Waiting for gateway agent to complete scan…'
              : activeScanCommandId && allScanSubnets.length === 0
                ? 'No scan results yet — wait for the agent or retry.'
                : allScanSubnets.length > 0
                  ? 'No subnets on this page.'
                  : 'Run a scan to discover subnets or probe a target CIDR.'
          }
        />
        {allScanSubnets.length > SCAN_PAGE_SIZE ? (
          <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-ink-mute-2">
            <p>
              Showing {(scanPage - 1) * SCAN_PAGE_SIZE + 1}–
              {Math.min(scanPage * SCAN_PAGE_SIZE, allScanSubnets.length)} of{' '}
              {allScanSubnets.length} subnets
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                disabled={scanPage <= 1}
                onClick={() => setScanPage((page) => Math.max(1, page - 1))}
              >
                Previous
              </Button>
              <span>
                Page {scanPage} of {scanPageCount}
              </span>
              <Button
                variant="secondary"
                disabled={scanPage >= scanPageCount}
                onClick={() =>
                  setScanPage((page) => Math.min(scanPageCount, page + 1))
                }
              >
                Next
              </Button>
            </div>
          </div>
        ) : null}
        {expandedSubnet ? (
          <div className="rounded-sm border border-hairline bg-canvas-night p-3">
            <h4 className="mb-2 text-xs font-medium text-ink-mute-2">
              Hosts in{' '}
              {allScanSubnets.find(
                (subnet) => scanSubnetRowKey(subnet) === expandedSubnet,
              )?.cidr ?? expandedSubnet}
            </h4>
            <ul className="space-y-1 text-sm">
              {(allScanSubnets.find(
                (subnet) => scanSubnetRowKey(subnet) === expandedSubnet,
              )?.hosts ?? []
              ).map((host) => (
                <li
                  key={host.ip}
                  className="flex flex-wrap items-center gap-2 font-mono text-xs"
                >
                  <span className="text-primary">{host.ip}</span>
                  {host.hostname ? (
                    <span className="text-ink-mute-2">{host.hostname}</span>
                  ) : null}
                  {host.mac ? (
                    <span className="text-ink-mute-2">{host.mac}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>

      <TailscaleConnectPanel
        gateway={gateway}
        scanRefreshKey={scanRefreshKey}
        onSuccess={(message) => {
          setActionError(null)
          setActionMessage(message)
          void loadGateway()
        }}
        onError={(message) => {
          setActionMessage(null)
          setActionError(message)
        }}
      />

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-medium text-white">Routes sync</h3>
            <p className="text-xs text-ink-mute-2">
              Approved and enabled routes from Headscale
            </p>
          </div>
          <Button
            variant="secondary"
            disabled={routesLoading}
            onClick={() => void loadRoutes()}
          >
            {routesLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <RefreshCw className="h-4 w-4" aria-hidden />
            )}
            Sync routes
          </Button>
        </div>
        {routesError ? (
          <p
            role="alert"
            className="rounded-sm border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200"
          >
            {routesError}
          </p>
        ) : null}
        <DataTable
          columns={routeColumns}
          rows={routes}
          rowKey={(row) => row.cidr}
          emptyMessage="No routes synced from Headscale."
        />
      </section>
        </>
      ) : null}

      {deleteConfirmOpen ? (
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
                setDeleteConfirmOpen(false)
              }
            }}
          />
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="gateway-delete-title"
            aria-describedby="gateway-delete-body"
            className="relative z-10 w-full max-w-md rounded-md border border-hairline bg-canvas-night-soft shadow-xl"
          >
            <div className="border-b border-hairline px-5 py-4">
              <h2
                id="gateway-delete-title"
                className="text-base font-semibold text-white"
              >
                Delete gateway
              </h2>
            </div>
            <div className="px-5 py-4">
              <p id="gateway-delete-body" className="text-sm text-ink-mute-2">
                Permanently delete{' '}
                <span className="font-medium text-white">
                  {gateway.hostname || 'this gateway'}
                </span>
                ? The enrolled agent token will be revoked. The remote agent must
                re-enroll to connect again.
              </p>
            </div>
            <div className="flex justify-end gap-2 border-t border-hairline px-5 py-4">
              <Button
                variant="secondary"
                disabled={deleting}
                onClick={() => setDeleteConfirmOpen(false)}
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
