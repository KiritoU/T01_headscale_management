import { Copy, Loader2, Server, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Button } from '../ui/Button'
import { api, getApiBaseUrl } from '../../lib/api'
import { copyToClipboard } from '../../lib/clipboard'
import {
  buildWorkerEnrollmentCurl,
  formatExpiryCountdown,
} from '../../lib/format'
import type { WorkerEnrollmentToken } from '../../types'

interface AddWorkerModalProps {
  open: boolean
  onClose: () => void
  /** Called after enrollment token is created so the parent can watch for agent connection. */
  onEnrollmentTokenCreated?: (workerId: string, workerName: string) => void
  watchingEnrollment?: boolean
}

export function AddWorkerModal({
  open,
  onClose,
  onEnrollmentTokenCreated,
  watchingEnrollment = false,
}: AddWorkerModalProps) {
  const [name, setName] = useState('')
  const [expiresInMinutes, setExpiresInMinutes] = useState(60)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [enrollment, setEnrollment] = useState<WorkerEnrollmentToken | null>(
    null,
  )
  const [copying, setCopying] = useState(false)
  const [copied, setCopied] = useState(false)
  const [copyMessage, setCopyMessage] = useState<string | null>(null)
  const [countdown, setCountdown] = useState('')

  const resetForm = useCallback(() => {
    setName('')
    setExpiresInMinutes(60)
    setSubmitting(false)
    setError(null)
    setEnrollment(null)
    setCopying(false)
    setCopied(false)
    setCopyMessage(null)
    setCountdown('')
  }, [])

  const handleClose = useCallback(() => {
    resetForm()
    onClose()
  }, [onClose, resetForm])

  useEffect(() => {
    if (!open) {
      return
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        handleClose()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, handleClose])

  useEffect(() => {
    if (!enrollment?.expires_at) {
      return
    }
    const tick = () => {
      setCountdown(formatExpiryCountdown(enrollment.expires_at))
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [enrollment?.expires_at])

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    const trimmedName = name.trim()
    if (!trimmedName) {
      setError('Worker name is required.')
      return
    }

    setSubmitting(true)
    setError(null)
    try {
      const result = await api.createWorkerEnrollmentToken(
        trimmedName,
        expiresInMinutes,
      )
      setEnrollment(result)
      onEnrollmentTokenCreated?.(result.worker_id, result.name)
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to create enrollment token',
      )
    } finally {
      setSubmitting(false)
    }
  }

  const handleCopy = async () => {
    if (!enrollment) {
      return
    }
    setCopying(true)
    setCopyMessage(null)
    try {
      const curl = buildWorkerEnrollmentCurl(getApiBaseUrl(), enrollment.token)
      await copyToClipboard(curl)
      setCopied(true)
      setCopyMessage('Install command copied to clipboard.')
      setTimeout(() => {
        setCopied(false)
        setCopyMessage(null)
      }, 2500)
    } catch {
      setCopyMessage('Could not copy — select the command above and copy manually.')
    } finally {
      setCopying(false)
    }
  }

  if (!open) {
    return null
  }

  const curlCommand = enrollment
    ? buildWorkerEnrollmentCurl(getApiBaseUrl(), enrollment.token)
    : ''

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="presentation"
    >
      <button
        type="button"
        aria-label="Close modal"
        className="absolute inset-0 cursor-pointer bg-black/60"
        onClick={handleClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-worker-title"
        className="relative z-10 w-full max-w-lg rounded-md border border-hairline bg-canvas-night-soft shadow-xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-hairline px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-sm bg-primary/15 text-primary">
              <Server className="h-4 w-4" aria-hidden />
            </span>
            <div>
              <h2
                id="add-worker-title"
                className="text-base font-semibold text-white"
              >
                Add new worker
              </h2>
              <p className="text-xs text-ink-mute-2">
                Enroll a VPS host to run tenant stacks
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="cursor-pointer rounded-sm p-1 text-ink-mute-2 transition-colors hover:bg-white/5 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            aria-label="Close"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>

        <div className="px-5 py-4">
          {enrollment ? (
            <div className="space-y-4">
              <div
                role="status"
                className="rounded-sm border border-primary/30 bg-primary/10 px-4 py-3 text-sm text-primary"
              >
                Enrollment token created for{' '}
                <span className="font-medium">{enrollment.name}</span>. Run the
                command below on the target Linux VPS.
                {watchingEnrollment ? (
                  <span className="mt-2 flex items-center gap-2 text-primary/90">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                    Waiting for worker agent to connect…
                  </span>
                ) : (
                  <span className="mt-2 block text-primary/80">
                    The worker list updates automatically after the agent enrolls.
                  </span>
                )}
              </div>

              <div className="space-y-2">
                <label className="text-xs font-medium uppercase tracking-wide text-ink-mute-2">
                  Install command
                </label>
                <pre className="overflow-x-auto rounded-sm border border-hairline bg-canvas-night p-3 font-mono text-xs leading-relaxed text-white">
                  {curlCommand}
                </pre>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-ink-mute-2">
                  {countdown || formatExpiryCountdown(enrollment.expires_at)}
                </p>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={copying}
                  onClick={() => void handleCopy()}
                >
                  {copying ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : (
                    <Copy className="h-4 w-4" aria-hidden />
                  )}
                  {copied ? 'Copied!' : 'Copy command'}
                </Button>
              </div>

              {copyMessage ? (
                <p
                  role="status"
                  className={`text-sm ${
                    copied ? 'text-primary' : 'text-amber-200'
                  }`}
                >
                  {copyMessage}
                </p>
              ) : null}

              <p className="text-xs text-ink-mute-2">
                Run this one-liner as root on the target Linux VPS. The worker
                will appear here once enrollment completes.
              </p>
            </div>
          ) : (
            <form className="space-y-4" onSubmit={(e) => void handleSubmit(e)}>
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="text-ink-mute-2">Worker name</span>
                <input
                  type="text"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="e.g. worker-east-1"
                  required
                  autoFocus
                  className="rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-white placeholder:text-ink-faint focus:border-primary focus:outline-none"
                />
              </label>

              <label className="flex flex-col gap-1.5 text-sm">
                <span className="text-ink-mute-2">Token expiry (minutes)</span>
                <input
                  type="number"
                  min={1}
                  max={10080}
                  value={expiresInMinutes}
                  onChange={(event) =>
                    setExpiresInMinutes(Number(event.target.value) || 60)
                  }
                  className="rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-white focus:border-primary focus:outline-none"
                />
              </label>

              {error ? (
                <div
                  role="alert"
                  className="rounded-sm border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200"
                >
                  {error}
                </div>
              ) : null}

              <div className="flex justify-end gap-2 pt-2">
                <Button variant="secondary" type="button" onClick={handleClose}>
                  Cancel
                </Button>
                <Button type="submit" disabled={submitting}>
                  {submitting ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : null}
                  Generate install command
                </Button>
              </div>
            </form>
          )}
        </div>

        {enrollment ? (
          <div className="flex justify-end border-t border-hairline px-5 py-4">
            <Button onClick={handleClose}>Done</Button>
          </div>
        ) : null}
      </div>
    </div>
  )
}
