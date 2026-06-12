import { Loader2, Network } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Button } from '../ui/Button'
import { ErrorState, LoadingState } from '../ui/PageState'
import { api } from '../../lib/api'
import {
  buildAdvertiseRoutes,
  createEmptyRouteSelection,
  hasRouteSelection,
  type RouteSelectionState,
} from '../../lib/tailscaleConnect'
import type { Gateway, TailscaleConnectContext, TailscaleUpOptions } from '../../types'
import { RouteSelectionTree } from './RouteSelectionTree'
import { TailscaleOptionToggles } from './TailscaleOptionToggles'
import { TenantPicker } from './TenantPicker'

interface TailscaleConnectPanelProps {
  gateway: Gateway
  scanRefreshKey?: number
  onSuccess?: (message: string) => void
  onError?: (message: string) => void
}

export function TailscaleConnectPanel({
  gateway,
  scanRefreshKey = 0,
  onSuccess,
  onError,
}: TailscaleConnectPanelProps) {
  const [context, setContext] = useState<TailscaleConnectContext | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedTenantId, setSelectedTenantId] = useState('')
  const [selection, setSelection] = useState<RouteSelectionState>(
    createEmptyRouteSelection(),
  )
  const [options, setOptions] = useState<TailscaleUpOptions>({
    force_reauth: true,
    accept_dns: true,
    reset: true,
  })
  const [submitting, setSubmitting] = useState(false)

  const hasTailscale = gateway.installed_modules.includes('tailscale')

  const loadContext = useCallback(
    async (tenantId?: string) => {
      setLoading(true)
      setError(null)
      try {
        const data = await api.getTailscaleConnectContext(
          gateway.id,
          tenantId,
        )
        setContext(data)
        setSelectedTenantId(data.tenant_preview.tenant_id)
        setOptions(data.option_defaults)
        setSelection(createEmptyRouteSelection())
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : 'Failed to load Tailscale connect context',
        )
        setContext(null)
      } finally {
        setLoading(false)
      }
    },
    [gateway.id],
  )

  useEffect(() => {
    void loadContext()
  }, [loadContext])

  useEffect(() => {
    if (scanRefreshKey === 0) {
      return
    }
    void loadContext(selectedTenantId || undefined)
  }, [scanRefreshKey, loadContext, selectedTenantId])

  const handleTenantChange = (tenantId: string) => {
    setSelectedTenantId(tenantId)
    void loadContext(tenantId)
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!context) {
      return
    }

    const subnets = context.last_scan?.subnets ?? []
    const advertiseRoutes = buildAdvertiseRoutes(selection, subnets)
    const selectedTenant = context.tenants.find(
      (tenant) => tenant.id === selectedTenantId,
    )

    if (!selectedTenant?.credentials_ready) {
      onError?.('Tenant credentials are not ready for Tailscale connect.')
      return
    }

    if (advertiseRoutes.length === 0) {
      onError?.('Select at least one subnet or host to advertise.')
      return
    }

    setSubmitting(true)
    try {
      const result = await api.sendGatewayCommand(gateway.id, {
        command: 'tailscale_up',
        payload: {
          tenant_id: selectedTenantId,
          advertise_routes: advertiseRoutes,
          force_reauth: options.force_reauth,
          accept_dns: options.accept_dns,
          reset: options.reset,
        },
      })
      onSuccess?.(
        `Tailscale up command queued (${result.id.slice(0, 8)}…, state: ${result.state})`,
      )
    } catch (err) {
      onError?.(
        err instanceof Error ? err.message : 'Failed to dispatch Tailscale up',
      )
    } finally {
      setSubmitting(false)
    }
  }

  const selectedTenant = context?.tenants.find(
    (tenant) => tenant.id === selectedTenantId,
  )
  const credentialsReady = selectedTenant?.credentials_ready ?? false
  const routesSelected = hasRouteSelection(selection)
  const canSubmit =
    hasTailscale && credentialsReady && routesSelected && !submitting && !loading

  if (loading && !context) {
    return <LoadingState message="Loading Tailscale connect options…" />
  }

  if (error && !context) {
    return (
      <ErrorState
        message={error}
        onRetry={() => void loadContext(selectedTenantId || undefined)}
      />
    )
  }

  if (!context) {
    return null
  }

  const scanSubnets = context.last_scan?.subnets ?? []

  return (
    <section className="space-y-4 rounded-md border border-hairline bg-canvas-night-soft p-4">
      <div className="flex items-center gap-2">
        <Network className="h-4 w-4 text-primary" aria-hidden />
        <h3 className="text-sm font-medium text-white">Tailscale connect</h3>
      </div>

      {!hasTailscale ? (
        <p className="text-sm text-ink-mute-2">
          Install the Tailscale module before reconnecting.
        </p>
      ) : null}

      {context.last_scan ? (
        <p className="text-xs text-ink-mute-2">
          Routes from last{' '}
          {context.last_scan.scan_mode === 'target' ? 'target CIDR' : 'discover'}{' '}
          scan ({context.last_scan.subnets.length} subnet
          {context.last_scan.subnets.length === 1 ? '' : 's'},{' '}
          {context.last_scan.summary.total_hosts} live host
          {context.last_scan.summary.total_hosts === 1 ? '' : 's'}).
        </p>
      ) : null}

      <form className="space-y-4" onSubmit={(event) => void handleSubmit(event)}>
        <TenantPicker
          tenants={context.tenants}
          selectedTenantId={selectedTenantId}
          gatewayTenantId={context.gateway_tenant_id}
          tenantPreview={context.tenant_preview}
          onChange={handleTenantChange}
          disabled={!hasTailscale || submitting}
        />

        <RouteSelectionTree
          subnets={scanSubnets}
          selection={selection}
          onChange={setSelection}
          disabled={!hasTailscale || submitting}
        />

        <TailscaleOptionToggles
          options={options}
          onChange={setOptions}
          disabled={!hasTailscale || submitting}
        />

        {!credentialsReady ? (
          <p className="text-xs text-amber-200">
            Bootstrap the selected tenant and ensure gateway auth keys exist
            before connecting.
          </p>
        ) : null}

        {!routesSelected && scanSubnets.length > 0 ? (
          <p className="text-xs text-ink-mute-2">
            Select subnets or individual hosts to advertise as routes.
          </p>
        ) : null}

        <Button type="submit" disabled={!canSubmit}>
          {submitting ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : null}
          Reconnect (tailscale up)
        </Button>
      </form>
    </section>
  )
}
