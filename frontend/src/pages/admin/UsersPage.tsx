import { Loader2, Plus, Trash2, Users } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { DataTable, type Column } from '../../components/ui/DataTable'
import { ErrorState, LoadingState } from '../../components/ui/PageState'
import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import type {
  AccessLevel,
  AuthUser,
  ResourceGrant,
  Role,
  ScopeType,
} from '../../types'

const ROLE_OPTIONS: Role[] = ['admin', 'editor', 'viewer']
const SCOPE_TYPE_OPTIONS: ScopeType[] = ['tenant', 'worker', 'gateway']
const ACCESS_LEVEL_OPTIONS: AccessLevel[] = ['view', 'edit']

interface ScopeOption {
  id: string
  label: string
}

export function UsersPage() {
  const [users, setUsers] = useState<AuthUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null)
  const [grants, setGrants] = useState<ResourceGrant[]>([])
  const [grantsLoading, setGrantsLoading] = useState(false)
  const [grantsError, setGrantsError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const [createUsername, setCreateUsername] = useState('')
  const [createPassword, setCreatePassword] = useState('')
  const [createRole, setCreateRole] = useState<Role>('viewer')
  const [createEmail, setCreateEmail] = useState('')

  const [grantScopeType, setGrantScopeType] = useState<ScopeType>('tenant')
  const [grantScopeId, setGrantScopeId] = useState('')
  const [grantAccessLevel, setGrantAccessLevel] = useState<AccessLevel>('view')

  const [scopeOptions, setScopeOptions] = useState<ScopeOption[]>([])
  const [scopeLoading, setScopeLoading] = useState(false)

  const selectedUser = users.find((user) => user.id === selectedUserId) ?? null

  const loadUsers = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listAdminUsers()
      setUsers(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load users')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadGrants = useCallback(async (userId: string) => {
    setGrantsLoading(true)
    setGrantsError(null)
    try {
      const data = await api.listUserGrants(userId)
      setGrants(data)
    } catch (err) {
      setGrantsError(err instanceof Error ? err.message : 'Failed to load grants')
      setGrants([])
    } finally {
      setGrantsLoading(false)
    }
  }, [])

  const loadScopeOptions = useCallback(async (scopeType: ScopeType) => {
    setScopeLoading(true)
    try {
      if (scopeType === 'tenant') {
        const tenants = await api.listTenants()
        setScopeOptions(
          tenants.map((tenant) => ({
            id: tenant.id,
            label: tenant.slug,
          })),
        )
      } else if (scopeType === 'worker') {
        const workers = await api.listWorkers()
        setScopeOptions(
          workers.map((worker) => ({
            id: worker.id,
            label: worker.name,
          })),
        )
      } else {
        const gateways = await api.listGateways()
        setScopeOptions(
          gateways.map((gateway) => ({
            id: gateway.id,
            label: `${gateway.hostname} (${gateway.tenant_slug})`,
          })),
        )
      }
    } catch {
      setScopeOptions([])
    } finally {
      setScopeLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadUsers()
  }, [loadUsers])

  useEffect(() => {
    if (!selectedUserId) {
      setGrants([])
      return
    }
    void loadGrants(selectedUserId)
  }, [selectedUserId, loadGrants])

  useEffect(() => {
    void loadScopeOptions(grantScopeType)
  }, [grantScopeType, loadScopeOptions])

  useEffect(() => {
    if (scopeOptions.length === 0) {
      setGrantScopeId('')
      return
    }
    if (!scopeOptions.some((option) => option.id === grantScopeId)) {
      setGrantScopeId(scopeOptions[0]?.id ?? '')
    }
  }, [scopeOptions, grantScopeId])

  const handleCreateUser = async (event: React.FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    setActionError(null)
    setActionMessage(null)
    try {
      const created = await api.createAdminUser({
        username: createUsername.trim(),
        password: createPassword,
        role: createRole,
        email: createEmail.trim() || undefined,
      })
      setUsers((current) =>
        [...current, created].sort((a, b) => a.username.localeCompare(b.username)),
      )
      setCreateUsername('')
      setCreatePassword('')
      setCreateEmail('')
      setCreateRole('viewer')
      setActionMessage(`Created user ${created.username}`)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to create user')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDeleteUser = async (user: AuthUser) => {
    if (!window.confirm(`Delete user "${user.username}"?`)) {
      return
    }
    setActionError(null)
    setActionMessage(null)
    try {
      await api.deleteAdminUser(user.id)
      setUsers((current) => current.filter((entry) => entry.id !== user.id))
      if (selectedUserId === user.id) {
        setSelectedUserId(null)
      }
      setActionMessage(`Deleted user ${user.username}`)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to delete user')
    }
  }

  const handleCreateGrant = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!selectedUserId || !grantScopeId) {
      return
    }
    setSubmitting(true)
    setActionError(null)
    setActionMessage(null)
    try {
      const created = await api.createUserGrant(selectedUserId, {
        scope_type: grantScopeType,
        scope_id: grantScopeId,
        access_level: grantAccessLevel,
      })
      setGrants((current) => [...current, created])
      setActionMessage('Grant created')
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to create grant')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDeleteGrant = async (grant: ResourceGrant) => {
    setActionError(null)
    setActionMessage(null)
    try {
      await api.deleteGrant(grant.id)
      setGrants((current) => current.filter((entry) => entry.id !== grant.id))
      setActionMessage('Grant removed')
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to delete grant')
    }
  }

  const userColumns = useMemo<Column<AuthUser>[]>(
    () => [
      {
        key: 'username',
        header: 'Username',
        render: (row) => (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              setSelectedUserId(row.id)
            }}
            className="cursor-pointer font-medium text-primary hover:text-primary-soft"
          >
            {row.username}
          </button>
        ),
      },
      {
        key: 'role',
        header: 'Role',
        render: (row) => (
          <span className="capitalize text-white">{row.role}</span>
        ),
      },
      {
        key: 'email',
        header: 'Email',
        render: (row) => (
          <span className="text-ink-mute-2">{row.email || '—'}</span>
        ),
      },
      {
        key: 'is_active',
        header: 'Active',
        render: (row) => (
          <span className={row.is_active ? 'text-primary' : 'text-ink-mute-2'}>
            {row.is_active ? 'Yes' : 'No'}
          </span>
        ),
      },
      {
        key: 'created_at',
        header: 'Created',
        render: (row) => (
          <span className="text-ink-mute-2">{formatDateTime(row.created_at)}</span>
        ),
      },
      {
        key: 'actions',
        header: '',
        render: (row) => (
          <Button
            variant="ghost"
            className="px-2 py-1 text-red-300 hover:text-red-200"
            onClick={(event) => {
              event.stopPropagation()
              void handleDeleteUser(row)
            }}
          >
            <Trash2 className="h-4 w-4" aria-hidden />
            <span className="sr-only">Delete {row.username}</span>
          </Button>
        ),
      },
    ],
    [],
  )

  const grantColumns = useMemo<Column<ResourceGrant>[]>(
    () => [
      {
        key: 'scope_type',
        header: 'Scope type',
        render: (row) => (
          <span className="capitalize text-white">{row.scope_type}</span>
        ),
      },
      {
        key: 'scope_id',
        header: 'Scope ID',
        render: (row) => (
          <span className="font-mono text-xs text-ink-mute-2">{row.scope_id}</span>
        ),
      },
      {
        key: 'access_level',
        header: 'Access',
        render: (row) => (
          <span className="capitalize text-white">{row.access_level}</span>
        ),
      },
      {
        key: 'created_at',
        header: 'Granted',
        render: (row) => (
          <span className="text-ink-mute-2">{formatDateTime(row.created_at)}</span>
        ),
      },
      {
        key: 'actions',
        header: '',
        render: (row) => (
          <Button
            variant="ghost"
            className="px-2 py-1 text-red-300 hover:text-red-200"
            onClick={() => void handleDeleteGrant(row)}
          >
            <Trash2 className="h-4 w-4" aria-hidden />
            <span className="sr-only">Remove grant</span>
          </Button>
        ),
      },
    ],
    [],
  )

  if (loading) {
    return <LoadingState message="Loading users…" />
  }

  if (error) {
    return <ErrorState message={error} onRetry={() => void loadUsers()} />
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center gap-3">
        <Users className="h-6 w-6 text-primary" aria-hidden />
        <div>
          <h2 className="text-lg font-semibold text-white">Users</h2>
          <p className="text-sm text-ink-mute-2">
            Manage operator accounts and resource grants
          </p>
        </div>
      </div>

      {actionError ? (
        <div
          role="alert"
          className="rounded-sm border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200"
        >
          {actionError}
        </div>
      ) : null}
      {actionMessage ? (
        <div className="rounded-sm border border-primary/30 bg-primary/10 px-4 py-3 text-sm text-primary">
          {actionMessage}
        </div>
      ) : null}

      <section className="space-y-4">
        <h3 className="text-sm font-medium text-white">Create user</h3>
        <form
          onSubmit={handleCreateUser}
          className="grid gap-4 rounded-md border border-hairline bg-canvas-night-soft p-4 md:grid-cols-2 lg:grid-cols-5"
        >
          <div>
            <label htmlFor="create-username" className="mb-1 block text-xs text-ink-mute-2">
              Username
            </label>
            <input
              id="create-username"
              value={createUsername}
              onChange={(event) => setCreateUsername(event.target.value)}
              required
              className="w-full rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            />
          </div>
          <div>
            <label htmlFor="create-password" className="mb-1 block text-xs text-ink-mute-2">
              Password
            </label>
            <input
              id="create-password"
              type="password"
              value={createPassword}
              onChange={(event) => setCreatePassword(event.target.value)}
              required
              className="w-full rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            />
          </div>
          <div>
            <label htmlFor="create-role" className="mb-1 block text-xs text-ink-mute-2">
              Role
            </label>
            <select
              id="create-role"
              value={createRole}
              onChange={(event) => setCreateRole(event.target.value as Role)}
              className="w-full cursor-pointer rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            >
              {ROLE_OPTIONS.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="create-email" className="mb-1 block text-xs text-ink-mute-2">
              Email (optional)
            </label>
            <input
              id="create-email"
              type="email"
              value={createEmail}
              onChange={(event) => setCreateEmail(event.target.value)}
              className="w-full rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            />
          </div>
          <div className="flex items-end">
            <Button type="submit" disabled={submitting}>
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Plus className="h-4 w-4" aria-hidden />
              )}
              Create user
            </Button>
          </div>
        </form>
      </section>

      <section className="space-y-4">
        <h3 className="text-sm font-medium text-white">All users</h3>
        <DataTable
          columns={userColumns}
          rows={users}
          rowKey={(row) => row.id}
          onRowClick={(row) => setSelectedUserId(row.id)}
          emptyMessage="No users found."
        />
      </section>

      {selectedUser ? (
        <section className="space-y-4">
          <div>
            <h3 className="text-sm font-medium text-white">
              Grants for {selectedUser.username}
            </h3>
            <p className="text-xs text-ink-mute-2">
              Scoped permissions for workers, tenants, and gateways
            </p>
          </div>

          <form
            onSubmit={handleCreateGrant}
            className="grid gap-4 rounded-md border border-hairline bg-canvas-night-soft p-4 md:grid-cols-2 lg:grid-cols-4"
          >
            <div>
              <label htmlFor="grant-scope-type" className="mb-1 block text-xs text-ink-mute-2">
                Scope type
              </label>
              <select
                id="grant-scope-type"
                value={grantScopeType}
                onChange={(event) =>
                  setGrantScopeType(event.target.value as ScopeType)
                }
                className="w-full cursor-pointer rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
              >
                {SCOPE_TYPE_OPTIONS.map((scopeType) => (
                  <option key={scopeType} value={scopeType}>
                    {scopeType}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="grant-scope-id" className="mb-1 block text-xs text-ink-mute-2">
                Resource
              </label>
              <select
                id="grant-scope-id"
                value={grantScopeId}
                onChange={(event) => setGrantScopeId(event.target.value)}
                disabled={scopeLoading || scopeOptions.length === 0}
                className="w-full cursor-pointer rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:opacity-50"
              >
                {scopeOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="grant-access" className="mb-1 block text-xs text-ink-mute-2">
                Access level
              </label>
              <select
                id="grant-access"
                value={grantAccessLevel}
                onChange={(event) =>
                  setGrantAccessLevel(event.target.value as AccessLevel)
                }
                className="w-full cursor-pointer rounded-sm border border-hairline-strong bg-canvas-night px-3 py-2 text-sm text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
              >
                {ACCESS_LEVEL_OPTIONS.map((level) => (
                  <option key={level} value={level}>
                    {level}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex items-end">
              <Button
                type="submit"
                disabled={submitting || !grantScopeId || scopeOptions.length === 0}
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Plus className="h-4 w-4" aria-hidden />
                )}
                Add grant
              </Button>
            </div>
          </form>

          {grantsLoading ? (
            <LoadingState message="Loading grants…" />
          ) : grantsError ? (
            <ErrorState
              message={grantsError}
              onRetry={() =>
                selectedUserId ? void loadGrants(selectedUserId) : undefined
              }
            />
          ) : (
            <DataTable
              columns={grantColumns}
              rows={grants}
              rowKey={(row) => row.id}
              emptyMessage="No grants for this user."
            />
          )}
        </section>
      ) : null}
    </div>
  )
}
