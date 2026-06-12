import type { ScanSubnet, TailscaleUpOptions } from '../types'

export type { TailscaleUpOptions }

export interface RouteSelectionState {
  selectedSubnets: Set<string>
  selectedHosts: Map<string, Set<string>>
}

export function createEmptyRouteSelection(): RouteSelectionState {
  return {
    selectedSubnets: new Set(),
    selectedHosts: new Map(),
  }
}

export function hasRouteSelection(selection: RouteSelectionState): boolean {
  if (selection.selectedSubnets.size > 0) {
    return true
  }
  for (const hosts of selection.selectedHosts.values()) {
    if (hosts.size > 0) {
      return true
    }
  }
  return false
}

export function buildAdvertiseRoutes(
  selection: RouteSelectionState,
  subnets: ScanSubnet[],
): string[] {
  const routes: string[] = []
  const seen = new Set<string>()

  for (const subnet of subnets) {
    const { cidr } = subnet

    if (selection.selectedSubnets.has(cidr)) {
      if (!seen.has(cidr)) {
        routes.push(cidr)
        seen.add(cidr)
      }
      continue
    }

    const hosts = selection.selectedHosts.get(cidr)
    if (!hosts) {
      continue
    }

    for (const ip of hosts) {
      const hostRoute = `${ip}/32`
      if (!seen.has(hostRoute)) {
        routes.push(hostRoute)
        seen.add(hostRoute)
      }
    }
  }

  return routes
}

export function toggleSubnet(
  selection: RouteSelectionState,
  cidr: string,
  selected: boolean,
): RouteSelectionState {
  const selectedSubnets = new Set(selection.selectedSubnets)
  const selectedHosts = new Map(selection.selectedHosts)

  if (selected) {
    selectedSubnets.add(cidr)
    selectedHosts.delete(cidr)
  } else {
    selectedSubnets.delete(cidr)
  }

  return { selectedSubnets, selectedHosts }
}

export function toggleHost(
  selection: RouteSelectionState,
  cidr: string,
  ip: string,
  selected: boolean,
): RouteSelectionState {
  if (selection.selectedSubnets.has(cidr)) {
    return selection
  }

  const selectedHosts = new Map(selection.selectedHosts)
  const hosts = new Set(selectedHosts.get(cidr) ?? [])

  if (selected) {
    hosts.add(ip)
  } else {
    hosts.delete(ip)
  }

  if (hosts.size === 0) {
    selectedHosts.delete(cidr)
  } else {
    selectedHosts.set(cidr, hosts)
  }

  return { ...selection, selectedHosts }
}

export function toggleAllSubnets(
  _selection: RouteSelectionState,
  subnets: ScanSubnet[],
  selected: boolean,
): RouteSelectionState {
  if (!selected) {
    return createEmptyRouteSelection()
  }

  return {
    selectedSubnets: new Set(subnets.map((subnet) => subnet.cidr)),
    selectedHosts: new Map(),
  }
}

export function areAllSubnetsSelected(
  selection: RouteSelectionState,
  subnets: ScanSubnet[],
): boolean {
  if (subnets.length === 0) {
    return false
  }
  return subnets.every((subnet) => selection.selectedSubnets.has(subnet.cidr))
}

export function isSubnetIndeterminate(
  selection: RouteSelectionState,
  subnet: ScanSubnet,
): boolean {
  if (selection.selectedSubnets.has(subnet.cidr)) {
    return false
  }
  const hosts = selection.selectedHosts.get(subnet.cidr)
  if (!hosts || hosts.size === 0) {
    return false
  }
  const liveHosts = subnet.hosts?.length ?? 0
  return liveHosts > 0 && hosts.size < liveHosts
}
