import { Building2, Network, Server } from 'lucide-react'
import { NavLink } from 'react-router-dom'

const navItems = [
  { to: '/tenants', label: 'Tenants', icon: Building2 },
  { to: '/workers', label: 'Workers', icon: Server },
  { to: '/gateways', label: 'Gateways', icon: Network },
] as const

export function Sidebar() {
  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-hairline bg-canvas-night-soft">
      <nav className="flex flex-1 flex-col gap-1 p-3" aria-label="Main navigation">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex cursor-pointer items-center gap-3 rounded-sm px-3 py-2 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary ${
                isActive
                  ? 'bg-primary/15 text-primary'
                  : 'text-ink-mute-2 hover:bg-white/5 hover:text-white'
              }`
            }
          >
            <Icon className="h-4 w-4 shrink-0" aria-hidden />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
