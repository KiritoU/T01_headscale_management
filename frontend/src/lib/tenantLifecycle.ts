import type { BootstrapStatus } from '../types'

/** Queue verify_tenant on the worker while a tenant detail page is open. */
export const TENANT_VERIFY_INTERVAL_MS = 60_000

/** Refresh tenant detail to pick up acked verify results between verify cycles. */
export const TENANT_HEALTH_REFRESH_INTERVAL_MS = 15_000

/** Hide manual bootstrap after auto-bootstrap (or any successful bootstrap) completes. */
export function shouldShowBootstrapButton(status: BootstrapStatus): boolean {
  return status !== 'bootstrapped'
}
