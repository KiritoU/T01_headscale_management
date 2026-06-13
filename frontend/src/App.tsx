import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { LoadingState } from './components/ui/PageState'
import { useAuth } from './contexts/auth'
import { UsersPage } from './pages/admin/UsersPage'
import { GatewayDetailPage } from './pages/GatewayDetailPage'
import { GatewaysPage } from './pages/GatewaysPage'
import { LoginPage } from './pages/LoginPage'
import { TenantDetailPage } from './pages/TenantDetailPage'
import { TenantsPage } from './pages/TenantsPage'
import { WorkerTenantDetailPage } from './pages/WorkerTenantDetailPage'
import { WorkerTenantsPage } from './pages/WorkerTenantsPage'
import { WorkersPage } from './pages/WorkersPage'

function ProtectedRoute() {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return <LoadingState message="Checking session…" />
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <Outlet />
}

function AdminRoute() {
  const { isAdmin, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return <LoadingState message="Checking session…" />
  }

  if (!isAdmin) {
    return <Navigate to="/tenants" state={{ from: location }} replace />
  }

  return <Outlet />
}

function InfrastructureRoute() {
  const { canManageInfrastructure, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return <LoadingState message="Checking session…" />
  }

  if (!canManageInfrastructure) {
    return <Navigate to="/tenants" state={{ from: location }} replace />
  }

  return <Outlet />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route index element={<Navigate to="/tenants" replace />} />
          <Route path="tenants" element={<TenantsPage />} />
          <Route path="tenants/:id" element={<TenantDetailPage />} />
          <Route element={<InfrastructureRoute />}>
            <Route path="workers" element={<WorkersPage />} />
            <Route path="workers/:workerId/tenants" element={<WorkerTenantsPage />} />
            <Route
              path="workers/:workerId/tenants/:tenantId"
              element={<WorkerTenantDetailPage />}
            />
            <Route path="gateways" element={<GatewaysPage />} />
            <Route path="gateways/:id" element={<GatewayDetailPage />} />
          </Route>
          <Route element={<AdminRoute />}>
            <Route path="admin/users" element={<UsersPage />} />
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/tenants" replace />} />
    </Routes>
  )
}
