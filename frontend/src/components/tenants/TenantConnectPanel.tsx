import { Check, Copy } from 'lucide-react'
import { useState } from 'react'
import { copyToClipboard } from '../../lib/clipboard'
import {
  buildTenantConnectCommand,
  buildTenantScriptUrl,
} from '../../lib/format'
import type { Tenant } from '../../types'

interface TenantConnectPanelProps {
  tenant: Pick<Tenant, 'slug' | 'desired_config' | 'connect_download_host'>
  workerAssigned?: boolean
}

function CopyableCommandRow({
  label,
  description,
  value,
}: {
  label: string
  description: string
  value: string
}) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await copyToClipboard(value)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="space-y-1.5 text-sm">
      <dt className="text-ink-mute-2">{label}</dt>
      <dd className="text-xs text-ink-mute-2">{description}</dd>
      <dd className="flex items-start gap-2">
        <code className="min-w-0 flex-1 break-all rounded-sm border border-hairline bg-canvas-night px-2 py-1.5 font-mono text-xs text-white">
          {value}
        </code>
        <button
          type="button"
          onClick={() => void handleCopy()}
          className="inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-sm border border-hairline bg-canvas-night px-2 py-1.5 text-xs text-ink-mute-2 hover:border-primary/40 hover:text-primary"
          aria-label={`Copy ${label}`}
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-primary" aria-hidden />
          ) : (
            <Copy className="h-3.5 w-3.5" aria-hidden />
          )}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </dd>
    </div>
  )
}

export function TenantConnectPanel({
  tenant,
  workerAssigned = false,
}: TenantConnectPanelProps) {
  const downloadHost = tenant.connect_download_host
  const linuxCommand = buildTenantConnectCommand(
    tenant.slug,
    'linux.sh',
    tenant.desired_config,
    downloadHost,
  )
  const gatewayCommand = buildTenantConnectCommand(
    tenant.slug,
    'gateway.sh',
    tenant.desired_config,
    downloadHost,
  )
  const windowsCommand = buildTenantConnectCommand(
    tenant.slug,
    'window.ps1',
    tenant.desired_config,
    downloadHost,
  )
  const linuxUrl = buildTenantScriptUrl(
    tenant.slug,
    'linux.sh',
    tenant.desired_config,
    downloadHost,
  )

  return (
    <section className="rounded-md border border-hairline bg-canvas-night-soft p-4">
      <div className="mb-3 space-y-1">
        <h3 className="text-sm font-medium text-white">Client connect</h3>
        <p className="text-xs text-ink-mute-2">
          Run on the target machine, then enter the auth key when prompted.
          Workspace nodes use the workspace key; subnet gateways use the
          gateway key from bootstrap below.
        </p>
        {workerAssigned ? (
          <p className="text-xs text-ink-mute-2">
            Scripts are served centrally from the console download host
            {downloadHost ? ` (${downloadHost})` : ''}.
          </p>
        ) : (
          <p className="text-xs text-amber-200/80">
            Assign and provision this tenant on a worker before scripts are
            available at the download host.
          </p>
        )}
      </div>

      <dl className="space-y-4">
        <CopyableCommandRow
          label="Workspace node (Linux)"
          description="Install Tailscale and join the tailnet as a workspace client."
          value={linuxCommand}
        />
        <CopyableCommandRow
          label="Subnet gateway (Linux)"
          description="Install Tailscale and advertise LAN subnets as a gateway."
          value={gatewayCommand}
        />
        <CopyableCommandRow
          label="Workspace node (Windows)"
          description="PowerShell one-liner for Windows workspace clients."
          value={windowsCommand}
        />
        <div className="space-y-1.5 text-sm">
          <dt className="text-ink-mute-2">Script URL (Linux)</dt>
          <dd>
            <a
              href={linuxUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="break-all font-mono text-xs text-primary hover:text-primary-soft"
            >
              {linuxUrl}
            </a>
          </dd>
        </div>
      </dl>
    </section>
  )
}
