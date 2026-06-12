import type { TailscaleUpOptions } from '../../types'

interface TailscaleOptionTogglesProps {
  options: TailscaleUpOptions
  onChange: (options: TailscaleUpOptions) => void
  disabled?: boolean
}

interface ToggleRowProps {
  id: string
  label: string
  description: string
  checked: boolean
  disabled?: boolean
  onChange: (checked: boolean) => void
}

function ToggleRow({
  id,
  label,
  description,
  checked,
  disabled = false,
  onChange,
}: ToggleRowProps) {
  return (
    <label
      htmlFor={id}
      className={`flex cursor-pointer items-start justify-between gap-4 rounded-sm border border-hairline bg-canvas-night px-3 py-3 ${disabled ? 'opacity-50' : ''}`}
    >
      <span className="flex flex-col gap-1">
        <span className="text-sm font-medium text-white">{label}</span>
        <span className="text-xs text-ink-mute-2">{description}</span>
      </span>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed ${checked ? 'bg-primary' : 'bg-hairline-strong'}`}
      >
        <span
          className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${checked ? 'translate-x-4' : 'translate-x-0'}`}
        />
      </button>
    </label>
  )
}

export function TailscaleOptionToggles({
  options,
  onChange,
  disabled = false,
}: TailscaleOptionTogglesProps) {
  const update = (patch: Partial<TailscaleUpOptions>) => {
    onChange({ ...options, ...patch })
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-mute-2">
        Connection options
      </p>
      <ToggleRow
        id="tailscale-force-reauth"
        label="Force re-authentication"
        description="Re-run login even if the node was previously authenticated."
        checked={options.force_reauth}
        disabled={disabled}
        onChange={(checked) => update({ force_reauth: checked })}
      />
      <ToggleRow
        id="tailscale-accept-dns"
        label="Accept DNS"
        description="Use the tailnet DNS settings from Headscale."
        checked={options.accept_dns}
        disabled={disabled}
        onChange={(checked) => update({ accept_dns: checked })}
      />
      <ToggleRow
        id="tailscale-reset"
        label="Reset state"
        description="Clear existing Tailscale state before reconnecting."
        checked={options.reset}
        disabled={disabled}
        onChange={(checked) => update({ reset: checked })}
      />
    </div>
  )
}
