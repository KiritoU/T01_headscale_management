import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import {
  areAllSubnetsSelected,
  isSubnetIndeterminate,
  toggleAllSubnets,
  toggleHost,
  toggleSubnet,
  type RouteSelectionState,
} from '../../lib/tailscaleConnect'
import type { ScanSubnet } from '../../types'

interface RouteSelectionTreeProps {
  subnets: ScanSubnet[]
  selection: RouteSelectionState
  onChange: (selection: RouteSelectionState) => void
  disabled?: boolean
}

const checkboxClassName =
  'h-4 w-4 shrink-0 rounded border-hairline-strong bg-canvas-night text-primary focus:ring-primary'

export function RouteSelectionTree({
  subnets,
  selection,
  onChange,
  disabled = false,
}: RouteSelectionTreeProps) {
  const [expandedSubnets, setExpandedSubnets] = useState<Set<string>>(new Set())

  const allSelected = areAllSubnetsSelected(selection, subnets)
  const someSelected =
    selection.selectedSubnets.size > 0 ||
    Array.from(selection.selectedHosts.values()).some((hosts) => hosts.size > 0)

  const toggleExpanded = (cidr: string) => {
    setExpandedSubnets((current) => {
      const next = new Set(current)
      if (next.has(cidr)) {
        next.delete(cidr)
      } else {
        next.add(cidr)
      }
      return next
    })
  }

  if (subnets.length === 0) {
    return (
      <p className="text-sm text-ink-mute-2">
        No scan results available. Run a network scan above to discover subnets
        and hosts for route advertisement.
      </p>
    )
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-mute-2">
        Advertise routes
      </p>

      <label className="flex cursor-pointer items-center gap-2 rounded-sm border border-hairline bg-canvas-night px-3 py-2 text-sm text-white">
        <input
          type="checkbox"
          className={checkboxClassName}
          checked={allSelected}
          ref={(element) => {
            if (element) {
              element.indeterminate = !allSelected && someSelected
            }
          }}
          disabled={disabled}
          onChange={(event) =>
            onChange(toggleAllSubnets(selection, subnets, event.target.checked))
          }
        />
        Select all subnets
      </label>

      <ul className="space-y-1">
        {subnets.map((subnet) => {
          const subnetSelected = selection.selectedSubnets.has(subnet.cidr)
          const indeterminate = isSubnetIndeterminate(selection, subnet)
          const expanded = expandedSubnets.has(subnet.cidr)
          const hosts = subnet.hosts ?? []
          const hasHosts = hosts.length > 0

          return (
            <li
              key={subnet.cidr}
              className="rounded-sm border border-hairline bg-canvas-night"
            >
              <div className="flex items-center gap-2 px-3 py-2">
                <input
                  type="checkbox"
                  className={checkboxClassName}
                  checked={subnetSelected}
                  ref={(element) => {
                    if (element) {
                      element.indeterminate = indeterminate
                    }
                  }}
                  disabled={disabled}
                  onChange={(event) =>
                    onChange(
                      toggleSubnet(selection, subnet.cidr, event.target.checked),
                    )
                  }
                />
                <span className="min-w-0 flex-1 font-mono text-xs text-white">
                  {subnet.cidr}
                </span>
                {subnet.is_local ? (
                  <span className="rounded-sm bg-primary/15 px-2 py-0.5 text-xs text-primary">
                    LAN
                  </span>
                ) : null}
                {subnet.live_hosts !== null ? (
                  <span className="text-xs text-ink-mute-2">
                    {subnet.live_hosts} host{subnet.live_hosts === 1 ? '' : 's'}
                  </span>
                ) : null}
                {hasHosts ? (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => toggleExpanded(subnet.cidr)}
                    className="cursor-pointer rounded-sm p-1 text-ink-mute-2 hover:bg-white/5 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:opacity-50"
                    aria-expanded={expanded}
                    aria-label={`${expanded ? 'Collapse' : 'Expand'} hosts in ${subnet.cidr}`}
                  >
                    {expanded ? (
                      <ChevronDown className="h-4 w-4" aria-hidden />
                    ) : (
                      <ChevronRight className="h-4 w-4" aria-hidden />
                    )}
                  </button>
                ) : null}
              </div>

              {expanded && hasHosts ? (
                <ul className="border-t border-hairline px-3 py-2 pl-9">
                  {hosts.map((host) => {
                    const hostSelected =
                      subnetSelected ||
                      (selection.selectedHosts.get(subnet.cidr)?.has(host.ip) ??
                        false)

                    return (
                      <li
                        key={host.ip}
                        className="flex items-center gap-2 py-1 text-sm"
                      >
                        <input
                          type="checkbox"
                          className={checkboxClassName}
                          checked={hostSelected}
                          disabled={disabled || subnetSelected}
                          onChange={(event) =>
                            onChange(
                              toggleHost(
                                selection,
                                subnet.cidr,
                                host.ip,
                                event.target.checked,
                              ),
                            )
                          }
                        />
                        <span className="font-mono text-xs text-primary">
                          {host.ip}
                        </span>
                        {host.hostname ? (
                          <span className="text-xs text-ink-mute-2">
                            {host.hostname}
                          </span>
                        ) : null}
                        {host.mac ? (
                          <span className="font-mono text-xs text-ink-mute-2">
                            {host.mac}
                          </span>
                        ) : null}
                      </li>
                    )
                  })}
                </ul>
              ) : null}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
