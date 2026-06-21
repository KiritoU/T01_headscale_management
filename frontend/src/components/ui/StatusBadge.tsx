import type {
  BootstrapStatus,
  GatewayStatus,
  RuntimeStatus,
  WorkerStatus,
} from '../../types'

type BadgeVariant = 'success' | 'warning' | 'danger' | 'neutral' | 'info'

const variantClasses: Record<BadgeVariant, string> = {
  success: 'bg-primary/15 text-primary border-primary/30',
  warning: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  danger: 'bg-red-500/15 text-red-300 border-red-500/30',
  neutral: 'bg-white/5 text-ink-mute-2 border-hairline',
  info: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
}

interface StatusBadgeProps {
  label: string
  variant?: BadgeVariant
}

export function StatusBadge({ label, variant = 'neutral' }: StatusBadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-sm border px-2 py-0.5 text-xs font-medium capitalize ${variantClasses[variant]}`}
    >
      {label}
    </span>
  )
}

const bootstrapVariants: Record<BootstrapStatus, BadgeVariant> = {
  pending: 'neutral',
  provisioning: 'info',
  bootstrapped: 'success',
  failed: 'danger',
}

const runtimeVariants: Record<RuntimeStatus, BadgeVariant> = {
  pending: 'neutral',
  provisioning: 'info',
  running: 'success',
  stopped: 'warning',
  failed: 'danger',
}

const workerVariants: Record<WorkerStatus, BadgeVariant> = {
  pending: 'neutral',
  online: 'success',
  offline: 'danger',
  disabled: 'warning',
}

const gatewayVariants: Record<GatewayStatus, BadgeVariant> = {
  pending: 'neutral',
  enrolled: 'info',
  online: 'success',
  offline: 'danger',
  disabled: 'warning',
}

export function BootstrapStatusBadge({ status }: { status: BootstrapStatus }) {
  return <StatusBadge label={status} variant={bootstrapVariants[status]} />
}

export function RuntimeStatusBadge({ status }: { status: RuntimeStatus }) {
  return <StatusBadge label={status} variant={runtimeVariants[status]} />
}

export function WorkerStatusBadge({ status }: { status: WorkerStatus }) {
  return <StatusBadge label={status} variant={workerVariants[status]} />
}

export function GatewayStatusBadge({ status }: { status: GatewayStatus }) {
  return <StatusBadge label={status} variant={gatewayVariants[status]} />
}

export function OnlineIndicator({ online }: { online: boolean }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span
        className={`h-2 w-2 shrink-0 rounded-full ${
          online ? 'bg-primary shadow-[0_0_6px_rgba(62,207,142,0.6)]' : 'bg-ink-mute-2/50'
        }`}
        aria-hidden
      />
      <span className="text-xs text-ink-mute-2">{online ? 'Online' : 'Offline'}</span>
    </span>
  )
}

const MODULE_LABELS: Record<string, string> = {
  tailscale: 'Tailscale',
  nmap: 'Nmap',
  masscan: 'Masscan',
  docker: 'Docker',
  'vuln-nse-pack': 'Vuln NSE',
  'iot-probes': 'IoT probes',
  nuclei: 'Nuclei',
}

export function ModuleBadge({ moduleName }: { moduleName: string }) {
  const label = MODULE_LABELS[moduleName] ?? moduleName
  const variant: BadgeVariant =
    moduleName === 'tailscale'
      ? 'success'
      : moduleName === 'nmap' || moduleName === 'masscan'
        ? 'info'
        : moduleName === 'docker'
          ? 'info'
          : 'neutral'

  return <StatusBadge label={label} variant={variant} />
}

export function BooleanBadge({
  value,
  trueLabel = 'yes',
  falseLabel = 'no',
}: {
  value: boolean
  trueLabel?: string
  falseLabel?: string
}) {
  return (
    <StatusBadge
      label={value ? trueLabel : falseLabel}
      variant={value ? 'success' : 'danger'}
    />
  )
}

const installStatusVariants = {
  installed: 'success',
  pending: 'warning',
  missing: 'danger',
} as const satisfies Record<string, BadgeVariant>

export function MonitorModuleStatusBadge({
  moduleId,
  status,
}: {
  moduleId: string
  status: keyof typeof installStatusVariants
}) {
  const label = MODULE_LABELS[moduleId] ?? moduleId
  return (
    <span className="inline-flex items-center gap-1.5">
      <StatusBadge label={label} variant="neutral" />
      <StatusBadge
        label={status}
        variant={installStatusVariants[status]}
      />
    </span>
  )
}
