import { AlertCircle, Loader2 } from 'lucide-react'

export function LoadingState({ message = 'Loading…' }: { message?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-ink-mute-2">
      <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden />
      <span>{message}</span>
    </div>
  )
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string
  onRetry?: () => void
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 rounded-md border border-red-500/30 bg-red-500/10 px-6 py-10 text-center"
    >
      <AlertCircle className="h-5 w-5 text-red-300" aria-hidden />
      <p className="text-sm text-red-200">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="cursor-pointer text-sm font-medium text-primary hover:text-primary-soft"
        >
          Try again
        </button>
      ) : null}
    </div>
  )
}
