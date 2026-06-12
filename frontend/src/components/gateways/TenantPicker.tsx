import { AlertTriangle } from 'lucide-react'
import type { TailscaleTenantOption, TenantTailscalePreview } from '../../types'

interface TenantPickerProps {
  tenants: TailscaleTenantOption[]
  selectedTenantId: string
  gatewayTenantId: string
  tenantPreview: TenantTailscalePreview
  onChange: (tenantId: string) => void
  disabled?: boolean
}

export function TenantPicker({
  tenants,
  selectedTenantId,
  gatewayTenantId,
  tenantPreview,
  onChange,
  disabled = false,
}: TenantPickerProps) {
  const selectedTenant = tenants.find((tenant) => tenant.id === selectedTenantId)
  const tenantDiffers = selectedTenantId !== gatewayTenantId

  return (
    <div className="space-y-3">
      <label className="flex flex-col gap-1 text-xs text-ink-mute-2">
        Target tenant
        <select
          value={selectedTenantId}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled || tenants.length === 0}
          className="cursor-pointer rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus:border-primary focus:outline-none disabled:opacity-50"
        >
          {tenants.length === 0 ? (
            <option value="">No tenants available</option>
          ) : null}
          {tenants.map((tenant) => (
            <option key={tenant.id} value={tenant.id}>
              {tenant.slug}
              {!tenant.credentials_ready ? ' (credentials pending)' : ''}
            </option>
          ))}
        </select>
      </label>

      {tenantDiffers ? (
        <div
          role="status"
          className="flex items-start gap-2 rounded-sm border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <p>
            This gateway was enrolled under a different tenant. Connecting to{' '}
            <span className="font-medium">{tenantPreview.slug}</span> will join
            that tailnet instead of the enrollment tenant.
          </p>
        </div>
      ) : null}

      <div className="grid gap-3 text-sm md:grid-cols-2">
        <div className="rounded-sm border border-hairline bg-canvas-night px-3 py-2">
          <p className="text-xs text-ink-mute-2">Login server</p>
          <p className="font-mono text-xs text-white">
            {tenantPreview.login_server || '—'}
          </p>
        </div>
        <div className="rounded-sm border border-hairline bg-canvas-night px-3 py-2">
          <p className="text-xs text-ink-mute-2">Credentials</p>
          {selectedTenant?.credentials_ready ? (
            <p className="text-white">
              Ready
              {tenantPreview.auth_key_hint ? (
                <span className="ml-1 font-mono text-xs text-ink-mute-2">
                  ({tenantPreview.auth_key_hint})
                </span>
              ) : null}
            </p>
          ) : (
            <p className="text-amber-200">
              Not ready — bootstrap the tenant and generate gateway auth keys
              first.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
