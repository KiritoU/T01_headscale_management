import type {
  GatewayCommandDetail,
  ScanSubnet,
  ScanSummary,
} from '../types'

export type ScanMode = 'discover' | 'target'

export interface ParsedScanResult {
  subnets: ScanSubnet[]
  nmapAvailable: boolean | null
  summary: ScanSummary | null
  scanMode: ScanMode | null
}

export function parseScanResult(command: GatewayCommandDetail): ParsedScanResult {
  const payloadMode = command.payload?.mode as ScanMode | undefined

  if (command.result?.subnets) {
    const scanMode = payloadMode ?? null
    return {
      subnets: command.result.subnets.map((subnet) => ({
        ...subnet,
        scan_mode: subnet.scan_mode ?? scanMode ?? undefined,
      })),
      nmapAvailable: command.result.nmap_available ?? null,
      summary: null,
      scanMode,
    }
  }

  const logs = command.result?.logs
  if (!logs) {
    return { subnets: [], nmapAvailable: null, summary: null, scanMode: null }
  }

  try {
    const body = JSON.parse(logs) as {
      subnets?: ScanSubnet[]
      modules_missing?: string[]
      modules_used?: string[]
      summary?: ScanSummary
      scan_mode?: ScanMode
    }
    const modulesMissing = body.modules_missing ?? []
    const modulesUsed = body.modules_used ?? []
    const nmapAvailable =
      modulesUsed.includes('nmap') ||
      (modulesMissing.length > 0 ? !modulesMissing.includes('nmap') : null)

    return {
      subnets: body.subnets ?? [],
      nmapAvailable,
      summary: body.summary ?? null,
      scanMode:
        body.scan_mode ??
        (command.payload?.mode as ScanMode | undefined) ??
        null,
    }
  } catch {
    return { subnets: [], nmapAvailable: null, summary: null, scanMode: null }
  }
}

export function resolveScanMode(
  command: GatewayCommandDetail,
  parsed: ParsedScanResult,
): ScanMode {
  if (parsed.scanMode === 'discover' || parsed.scanMode === 'target') {
    return parsed.scanMode
  }
  const payloadMode = command.payload?.mode
  if (payloadMode === 'discover' || payloadMode === 'target') {
    return payloadMode
  }
  return 'discover'
}

export function mergeScanSummaries(
  discover: ScanSummary | null,
  target: ScanSummary | null,
): ScanSummary | null {
  if (!discover && !target) {
    return null
  }
  return {
    subnet_count: (discover?.subnet_count ?? 0) + (target?.subnet_count ?? 0),
    total_hosts: (discover?.total_hosts ?? 0) + (target?.total_hosts ?? 0),
    local_networks:
      (discover?.local_networks ?? 0) + (target?.local_networks ?? 0),
    target_networks:
      (discover?.target_networks ?? 0) + (target?.target_networks ?? 0),
  }
}

export function scanSubnetRowKey(row: ScanSubnet): string {
  return `${row.scan_mode ?? 'unknown'}:${row.cidr}`
}
