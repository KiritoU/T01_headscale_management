import { Check, Copy } from 'lucide-react'
import { useState } from 'react'
import { copyToClipboard } from '../../lib/clipboard'
import { formatDateTime } from '../../lib/format'
import type { TenantBootstrapInfo } from '../../types'

interface TenantBootstrapPanelProps {
  bootstrapInfo: TenantBootstrapInfo | null
  bootstrapStatus: string
  bootstrapOutputRef?: string
}

function CopyableSecretRow({
  label,
  value,
}: {
  label: string
  value: string | null | undefined
}) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    if (!value) {
      return
    }
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
      <dd className="flex items-start gap-2">
        <code className="min-w-0 flex-1 break-all rounded-sm border border-hairline bg-canvas-night px-2 py-1.5 font-mono text-xs text-white">
          {value || '—'}
        </code>
        {value ? (
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
        ) : null}
      </dd>
    </div>
  )
}

export function TenantBootstrapPanel({
  bootstrapInfo,
  bootstrapStatus,
  bootstrapOutputRef,
}: TenantBootstrapPanelProps) {
  const info = bootstrapInfo ?? {
    command_id: null,
    acked_at: null,
    admin_user_id: null,
    api_key: null,
    auth_key_gateway: null,
    auth_key_workspace: null,
    output_ref: bootstrapOutputRef ?? null,
  }

  const hasSecrets =
    info.api_key || info.auth_key_gateway || info.auth_key_workspace || info.admin_user_id

  return (
    <section className="rounded-md border border-hairline bg-canvas-night-soft p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-sm font-medium text-white">Bootstrap</h3>
        <span className="text-xs uppercase tracking-wide text-ink-mute-2">
          {bootstrapStatus}
        </span>
      </div>

      {!hasSecrets && bootstrapStatus !== 'bootstrapped' ? (
        <p className="text-sm text-ink-mute-2">
          Bootstrap has not completed yet. Keys will appear here after bootstrap finishes.
        </p>
      ) : (
        <dl className="space-y-4">
          <CopyableSecretRow label="Admin user ID" value={info.admin_user_id} />
          <CopyableSecretRow label="API key" value={info.api_key} />
          <CopyableSecretRow label="Gateway auth key" value={info.auth_key_gateway} />
          <CopyableSecretRow label="Workspace auth key" value={info.auth_key_workspace} />
          {info.output_ref ? (
            <CopyableSecretRow label="Output ref" value={info.output_ref} />
          ) : null}
          {info.acked_at ? (
            <div className="flex justify-between gap-4 text-sm">
              <dt className="text-ink-mute-2">Bootstrapped at</dt>
              <dd className="text-white">{formatDateTime(info.acked_at)}</dd>
            </div>
          ) : null}
        </dl>
      )}
    </section>
  )
}
