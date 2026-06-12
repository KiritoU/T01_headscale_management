import { useEffect, useRef } from 'react'
import {
  TENANT_HEALTH_REFRESH_INTERVAL_MS,
  TENANT_VERIFY_INTERVAL_MS,
} from '../lib/tenantLifecycle'

interface UsePeriodicTenantVerifyOptions {
  enabled: boolean
  verify: () => Promise<unknown>
  refresh: () => Promise<void>
}

/** Enqueue verify on an interval and refresh tenant detail for health check results. */
export function usePeriodicTenantVerify({
  enabled,
  verify,
  refresh,
}: UsePeriodicTenantVerifyOptions): void {
  const verifyRef = useRef(verify)
  const refreshRef = useRef(refresh)
  verifyRef.current = verify
  refreshRef.current = refresh

  useEffect(() => {
    if (!enabled) {
      return
    }

    const runVerify = () => {
      void verifyRef.current().catch(() => undefined)
    }

    const runRefresh = () => {
      void refreshRef.current().catch(() => undefined)
    }

    runVerify()
    const verifyIntervalId = window.setInterval(
      runVerify,
      TENANT_VERIFY_INTERVAL_MS,
    )
    const refreshIntervalId = window.setInterval(
      runRefresh,
      TENANT_HEALTH_REFRESH_INTERVAL_MS,
    )

    return () => {
      window.clearInterval(verifyIntervalId)
      window.clearInterval(refreshIntervalId)
    }
  }, [enabled])
}
