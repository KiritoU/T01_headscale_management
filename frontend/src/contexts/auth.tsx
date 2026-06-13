import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api, bootstrapCsrf } from '../lib/api'
import type { AuthMeResponse, AuthUser, ResourceGrant, Role } from '../types'

interface AuthContextValue {
  user: AuthUser | null
  grants: ResourceGrant[]
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  role: Role | null
  isAdmin: boolean
  isViewer: boolean
  canManageInfrastructure: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [grants, setGrants] = useState<ResourceGrant[]>([])
  const [loading, setLoading] = useState(true)

  const applySession = useCallback((session: AuthMeResponse | null) => {
    if (session) {
      setUser(session.user)
      setGrants(session.grants)
      return
    }
    setUser(null)
    setGrants([])
  }, [])

  const refresh = useCallback(async () => {
    try {
      const session = await api.getMe()
      applySession(session)
    } catch {
      applySession(null)
    }
  }, [applySession])

  useEffect(() => {
    let cancelled = false

    async function bootstrap() {
      try {
        await bootstrapCsrf()
        if (cancelled) {
          return
        }
        await refresh()
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void bootstrap()
    return () => {
      cancelled = true
    }
  }, [refresh])

  const login = useCallback(
    async (username: string, password: string) => {
      const loggedInUser = await api.login(username, password)
      setUser(loggedInUser)
      const session = await api.getMe()
      applySession(session)
    },
    [applySession],
  )

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      applySession(null)
    }
  }, [applySession])

  const role = user?.role ?? null
  const isAdmin = role === 'admin'
  const isViewer = role === 'viewer'
  const canManageInfrastructure = role === 'admin' || role === 'editor'

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      grants,
      loading,
      login,
      logout,
      refresh,
      role,
      isAdmin,
      isViewer,
      canManageInfrastructure,
    }),
    [
      user,
      grants,
      loading,
      login,
      logout,
      refresh,
      role,
      isAdmin,
      isViewer,
      canManageInfrastructure,
    ],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
