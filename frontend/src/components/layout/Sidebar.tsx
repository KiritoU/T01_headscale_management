import { Building2, LogOut, Network, Server, Settings, Users } from 'lucide-react'
import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/auth'
import { Button } from '../ui/Button'

const ROLE_LABELS: Record<string, string> = {
  admin: 'Admin',
  editor: 'Editor',
  viewer: 'Viewer',
}

const baseNavItems = [
  { to: '/tenants', label: 'Tenants', icon: Building2 },
  { to: '/workers', label: 'Workers', icon: Server, requiresInfrastructure: true },
  { to: '/gateways', label: 'Gateways', icon: Network, requiresInfrastructure: true },
  { to: '/admin/users', label: 'Users', icon: Users, requiresAdmin: true },
  { to: '/admin/settings', label: 'Console settings', icon: Settings, requiresAdmin: true },
] as const

export function Sidebar() {
  const { user, logout, canManageInfrastructure, isAdmin } = useAuth()
  const navigate = useNavigate()
  const [loggingOut, setLoggingOut] = useState(false)

  const navItems = baseNavItems.filter((item) => {
    if ('requiresAdmin' in item && item.requiresAdmin) {
      return isAdmin
    }
    if ('requiresInfrastructure' in item && item.requiresInfrastructure) {
      return canManageInfrastructure
    }
    return true
  })

  const handleLogout = async () => {
    setLoggingOut(true)
    try {
      await logout()
      navigate('/login', { replace: true })
    } finally {
      setLoggingOut(false)
    }
  }

  return (
    <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-hairline bg-canvas-night-soft">
      <nav
        className="flex flex-1 flex-col gap-1 overflow-y-auto p-3"
        aria-label="Main navigation"
      >
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

      {user ? (
        <div className="shrink-0 border-t border-hairline p-3">
          <div className="mb-2 px-1">
            <p className="truncate text-sm font-medium text-white">{user.username}</p>
            <p className="text-xs text-ink-mute-2">
              {ROLE_LABELS[user.role] ?? user.role}
            </p>
          </div>
          <Button
            variant="ghost"
            onClick={() => void handleLogout()}
            disabled={loggingOut}
            aria-label="Sign out"
            className="w-full justify-start px-2"
          >
            <LogOut className="h-4 w-4 shrink-0" aria-hidden />
            {loggingOut ? 'Signing out…' : 'Sign out'}
          </Button>
        </div>
      ) : null}
    </aside>
  )
}
