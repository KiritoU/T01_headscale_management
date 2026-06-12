import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { GatewayDetailPage } from './pages/GatewayDetailPage'
import { GatewaysPage } from './pages/GatewaysPage'
import { TenantDetailPage } from './pages/TenantDetailPage'
import { TenantsPage } from './pages/TenantsPage'
import { WorkerTenantDetailPage } from './pages/WorkerTenantDetailPage'
import { WorkerTenantsPage } from './pages/WorkerTenantsPage'
import { WorkersPage } from './pages/WorkersPage'

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/tenants" replace />} />
        <Route path="tenants" element={<TenantsPage />} />
        <Route path="tenants/:id" element={<TenantDetailPage />} />
        <Route path="workers" element={<WorkersPage />} />
        <Route path="workers/:workerId/tenants" element={<WorkerTenantsPage />} />
        <Route
          path="workers/:workerId/tenants/:tenantId"
          element={<WorkerTenantDetailPage />}
        />
        <Route path="gateways" element={<GatewaysPage />} />
        <Route path="gateways/:id" element={<GatewayDetailPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/tenants" replace />} />
    </Routes>
  )
}
