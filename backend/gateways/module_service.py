from __future__ import annotations

from agents.models import AgentCommand, AgentModule, CommandState
from gateways.models import Gateway, GatewayMonitorPolicy
from gateways.services import enqueue_gateway_command

VULN_MODULE_DEFAULTS = ["nmap", "vuln-nse-pack", "iot-probes"]

BUNDLE_MODULES = frozenset({"vuln-nse-pack", "iot-probes", "nuclei"})


def required_modules(policy: GatewayMonitorPolicy, *, include_optional: bool = True) -> list[str]:
    modules = list(policy.vuln_modules or VULN_MODULE_DEFAULTS)
    if "nmap" not in modules:
        modules.insert(0, "nmap")
    if include_optional and policy.nuclei_enabled and "nuclei" not in modules:
        modules.append("nuclei")
    return modules


def vuln_modules_required(policy: GatewayMonitorPolicy) -> list[str]:
    """Core vuln modules — nuclei is optional and must not block the queue."""
    return required_modules(policy, include_optional=False)


def vuln_scan_modules(gateway: Gateway, policy: GatewayMonitorPolicy) -> list[str]:
    """Modules to run per vuln job — includes nuclei only when enabled and installed."""
    modules = list(vuln_modules_required(policy))
    if policy.nuclei_enabled and _gateway_has_module(gateway, "nuclei"):
        if "nuclei" not in modules:
            modules.append("nuclei")
    return modules


def discovery_required_modules() -> list[str]:
    return ["masscan"]


def _gateway_has_module(gateway: Gateway, module_name: str) -> bool:
    if gateway.agent_id is None:
        return False
    return AgentModule.objects.filter(agent_id=gateway.agent_id, name=module_name).exists()


def _pending_install_commands(gateway: Gateway, module_name: str | None = None) -> bool:
    if gateway.agent_id is None:
        return False
    queryset = AgentCommand.objects.filter(
        agent_id=gateway.agent_id,
        command="install_module",
        state__in=[CommandState.PENDING, CommandState.DISPATCHED],
    )
    if module_name is not None:
        queryset = queryset.filter(payload__module=module_name)
    return queryset.exists()


def _pending_scan_commands(gateway: Gateway) -> bool:
    if gateway.agent_id is None:
        return False
    return AgentCommand.objects.filter(
        agent_id=gateway.agent_id,
        command="scan_network",
        state__in=[CommandState.PENDING, CommandState.DISPATCHED],
    ).exists()


def pending_network_scan(gateway: Gateway) -> bool:
    return _pending_scan_commands(gateway)


def _pending_vuln_commands(gateway: Gateway) -> bool:
    if gateway.agent_id is None:
        return False
    return AgentCommand.objects.filter(
        agent_id=gateway.agent_id,
        command="vuln_scan",
        state__in=[CommandState.PENDING, CommandState.DISPATCHED],
    ).exists()


def missing_modules(gateway: Gateway, modules: list[str]) -> list[str]:
    return [name for name in modules if not _gateway_has_module(gateway, name)]


def module_statuses(gateway: Gateway, modules: list[str]) -> list[dict[str, str]]:
    statuses: list[dict[str, str]] = []
    for module_name in modules:
        if _gateway_has_module(gateway, module_name):
            statuses.append({"module_id": module_name, "status": "installed"})
        elif _pending_install_commands(gateway, module_name):
            statuses.append({"module_id": module_name, "status": "pending"})
        else:
            statuses.append({"module_id": module_name, "status": "missing"})
    return statuses


def ensure_modules_installed(
    gateway: Gateway,
    modules: list[str],
) -> bool:
    """Enqueue install_module for missing modules. Return True when all ready."""
    if gateway.agent_id is None:
        return False

    ready = True
    for module_name in modules:
        if _gateway_has_module(gateway, module_name):
            continue
        if _pending_install_commands(gateway, module_name):
            ready = False
            continue
        enqueue_gateway_command(
            gateway,
            "install_module",
            {"module": module_name},
        )
        ready = False
    return ready


def modules_ready(gateway: Gateway, modules: list[str]) -> bool:
    if gateway.agent_id is None:
        return False
    if missing_modules(gateway, modules):
        return False
    for module_name in modules:
        if _pending_install_commands(gateway, module_name):
            return False
    return True


def can_enqueue_discovery(gateway: Gateway) -> bool:
    if gateway.agent_id is None:
        return False
    if _pending_scan_commands(gateway):
        return False
    return modules_ready(gateway, discovery_required_modules())


def can_enqueue_vuln_scan(gateway: Gateway, policy: GatewayMonitorPolicy) -> bool:
    if not policy.vuln_scan_enabled:
        return False
    if gateway.agent_id is None:
        return False
    if _pending_scan_commands(gateway) or _pending_vuln_commands(gateway):
        return False
    return modules_ready(gateway, vuln_modules_required(policy))
