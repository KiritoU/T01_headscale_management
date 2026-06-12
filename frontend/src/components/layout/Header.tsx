export function Header() {
  return (
    <header className="flex h-14 shrink-0 items-center border-b border-hairline bg-canvas-night-soft px-6">
      <div className="flex items-center gap-3">
        <div
          className="flex h-8 w-8 items-center justify-center rounded-sm bg-primary/15 text-sm font-semibold text-primary"
          aria-hidden
        >
          HS
        </div>
        <div>
          <h1 className="text-sm font-semibold text-white">Headscale Management</h1>
          <p className="text-xs text-ink-mute-2">Control plane dashboard</p>
        </div>
      </div>
    </header>
  )
}
