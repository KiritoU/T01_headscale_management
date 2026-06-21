from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_daemon.masscan_scan import scan_host_ports_masscan
from agent_daemon.module_installer import NUCLEI_BINARY, _nuclei_installed

NmapRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]
MasscanRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]

NSE_SCRIPT_DIR = "/opt/hsm/nse"
IOT_PROBE_DIR = "/opt/hsm/iot-probes"

HTTPS_PORTS = frozenset({443, 8443, 9443})
NON_HTTP_PORTS = frozenset({1, 22, 53, 445, 3389})
COMMON_WEB_PORTS = (80, 443, 3000, 5000, 8000, 8080, 8081, 8443, 8888, 9000)

NUCLEI_BASE_FLAGS = ("-silent", "-jsonl", "-disable-update-check", "-ni", "-no-stdin")
NUCLEI_EXCLUDED_TAGS = ("dos", "intrusive", "fuzz", "bruteforce")
NUCLEI_BROAD_TAGS = "tech,exposure,misconfig,vuln,cve"
NUCLEI_BROAD_TIMEOUT_SECONDS = 300
NUCLEI_CURATED_TIMEOUT_SECONDS = 120

CURATED_NUCLEI_TEMPLATES: tuple[str, ...] = (
    "http/technologies/owasp-juice-shop-detected.yaml",
    "http/misconfiguration/node-express-dev-env.yaml",
    "http/misconfiguration/express-stack-trace.yaml",
    "http/misconfiguration/node-express-status.yaml",
    "http/exposures/apis/swagger-api.yaml",
    "http/miscellaneous/robots-txt.yaml",
    "http/misconfiguration/http-missing-security-headers.yaml",
    "http/vulnerabilities/generic/cors-misconfig.yaml",
)

JUICE_SHOP_TEMPLATE_IDS = ("owasp-juice-shop-detect",)

SECURITY_HEADERS: tuple[tuple[str, str, str], ...] = (
    ("x-frame-options", "medium", "Missing X-Frame-Options header"),
    ("content-security-policy", "medium", "Missing Content-Security-Policy header"),
    ("x-content-type-options", "low", "Missing X-Content-Type-Options header"),
)

EXPOSED_PATH_CHECKS: tuple[tuple[str, str, str, str], ...] = (
    ("GET", "/api/Challenges", "info", "Public API challenges endpoint exposed"),
    ("GET", "/ftp/", "high", "FTP directory listing exposed"),
    ("GET", "/robots.txt", "info", "robots.txt exposed"),
    ("POST", "/rest/user/login", "info", "User login API endpoint exposed"),
)


@dataclass(frozen=True)
class VulnFindingResult:
    ip: str
    source: str
    severity: str
    title: str
    finding_id: str
    details: dict[str, Any]


def run_vuln_scan(
    targets: list[str],
    *,
    nmap_runner: NmapRunner,
    modules: list[str] | None = None,
    open_ports: list[int] | None = None,
    masscan_runner: MasscanRunner | None = None,
) -> dict[str, Any]:
    modules = modules or []
    findings: list[dict[str, Any]] = []
    seen_finding_ids: set[str] = set()

    for ip in targets:
        resolved_ports = _resolve_open_ports(
            ip,
            open_ports,
            masscan_runner=masscan_runner,
        )

        if "nmap" in modules:
            _extend_unique(
                findings,
                seen_finding_ids,
                _run_nmap_nse(ip, resolved_ports, nmap_runner=nmap_runner),
            )

        if "iot-probes" in modules:
            _extend_unique(
                findings,
                seen_finding_ids,
                _run_iot_probes([ip]),
            )

        http_findings = _run_http_fingerprints(ip, resolved_ports)
        _extend_unique(findings, seen_finding_ids, http_findings)

        _extend_unique(
            findings,
            seen_finding_ids,
            _run_web_security_probes(ip, resolved_ports, http_findings),
        )

        if "nuclei" in modules:
            juice_shop_detected = any(
                finding.get("title") == "OWASP Juice Shop detected"
                for finding in http_findings
            )
            _extend_unique(
                findings,
                seen_finding_ids,
                _run_nuclei(
                    ip,
                    resolved_ports,
                    juice_shop_detected=juice_shop_detected,
                ),
            )

    return {
        "targets": targets,
        "findings": findings,
        "summary": {
            "target_count": len(targets),
            "finding_count": len(findings),
        },
    }


def _extend_unique(
    findings: list[dict[str, Any]],
    seen_finding_ids: set[str],
    new_findings: list[dict[str, Any]],
) -> None:
    for finding in new_findings:
        finding_id = str(finding.get("finding_id", "")).strip()
        if finding_id and finding_id in seen_finding_ids:
            continue
        if finding_id:
            seen_finding_ids.add(finding_id)
        findings.append(finding)


def _resolve_open_ports(
    ip: str,
    open_ports: list[int] | None,
    *,
    masscan_runner: MasscanRunner | None,
) -> list[int]:
    if open_ports:
        return sorted({int(port) for port in open_ports if int(port) > 0})

    if masscan_runner is not None:
        discovered = scan_host_ports_masscan(ip, masscan_runner=masscan_runner)
        if discovered:
            return list(discovered)

    return list(COMMON_WEB_PORTS)


def build_nuclei_targets(ip: str, open_ports: list[int]) -> list[str]:
    web_ports = [port for port in open_ports if port not in NON_HTTP_PORTS]
    if not web_ports:
        web_ports = list(COMMON_WEB_PORTS)

    targets: list[str] = []
    for port in sorted(set(web_ports)):
        if port in HTTPS_PORTS:
            targets.append(f"https://{ip}:{port}")
        elif port == 80:
            targets.append(f"http://{ip}")
        else:
            targets.append(f"http://{ip}:{port}")
    return targets


def _nuclei_templates_root() -> str:
    configured = os.environ.get("NUCLEI_TEMPLATES_DIR", "").strip()
    if configured and os.path.isdir(configured):
        return configured
    return "/root/nuclei-templates"


def _curated_nuclei_template_args() -> list[str]:
    args: list[str] = []
    root = _nuclei_templates_root()
    for relative_path in CURATED_NUCLEI_TEMPLATES:
        template_path = os.path.join(root, relative_path)
        if os.path.isfile(template_path):
            args.extend(["-t", template_path])
    return args


def _run_nuclei(
    ip: str,
    open_ports: list[int],
    *,
    juice_shop_detected: bool = False,
) -> list[dict[str, Any]]:
    if not _nuclei_installed():
        return []

    binary = NUCLEI_BINARY if os.path.isfile(NUCLEI_BINARY) else "nuclei"
    targets = build_nuclei_targets(ip, open_ports)
    if not targets:
        return []

    findings: list[dict[str, Any]] = []
    seen_finding_ids: set[str] = set()
    curated_args = _curated_nuclei_template_args()

    for target in targets:
        scan_specs: list[tuple[list[str], int]] = []
        if curated_args:
            scan_specs.append((curated_args, NUCLEI_CURATED_TIMEOUT_SECONDS))

        broad_args = ["-tags", NUCLEI_BROAD_TAGS]
        templates_root = _nuclei_templates_root()
        if os.path.isdir(templates_root):
            broad_args = ["-templates", templates_root, *broad_args]
        scan_specs.append((broad_args, NUCLEI_BROAD_TIMEOUT_SECONDS))

        if juice_shop_detected:
            scan_specs.insert(
                0,
                (
                    ["-id", ",".join(JUICE_SHOP_TEMPLATE_IDS)],
                    60,
                ),
            )

        for extra_args, timeout_seconds in scan_specs:
            command = [
                binary,
                "-target",
                target,
                *NUCLEI_BASE_FLAGS,
                *extra_args,
                "-etags",
                ",".join(NUCLEI_EXCLUDED_TAGS),
            ]
            findings.extend(
                _collect_nuclei_output(
                    command,
                    ip=ip,
                    target=target,
                    timeout_seconds=timeout_seconds,
                    seen_finding_ids=seen_finding_ids,
                ),
            )
    return findings


def _collect_nuclei_output(
    command: list[str],
    *,
    ip: str,
    target: str,
    timeout_seconds: int,
    seen_finding_ids: set[str],
) -> list[dict[str, Any]]:
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    findings: list[dict[str, Any]] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not _nuclei_finding_belongs_to_host(item, ip):
            continue
        template_id = str(item.get("template-id", item.get("templateID", "nuclei")))
        finding_id = f"nuclei:{template_id}:{target}"
        if finding_id in seen_finding_ids:
            continue
        seen_finding_ids.add(finding_id)
        findings.append(
            {
                "ip": ip,
                "source": "nuclei",
                "severity": str(item.get("info", {}).get("severity", "info")),
                "title": str(item.get("info", {}).get("name", template_id)),
                "finding_id": finding_id,
                "details": item,
            },
        )
    return findings


def _nuclei_finding_belongs_to_host(item: dict[str, Any], ip: str) -> bool:
    tags = item.get("info", {}).get("tags") or []
    if "global-matchers" in tags:
        return False

    host = str(item.get("host", "")).strip()
    if host and ip not in host:
        return False

    item_ip = str(item.get("ip", "")).strip()
    if item_ip and item_ip != ip:
        return False

    matched = str(item.get("matched-at", item.get("url", ""))).strip()
    if matched and ip not in matched:
        return False

    return True


def _run_nmap_nse(
    ip: str,
    open_ports: list[int],
    *,
    nmap_runner: NmapRunner,
) -> list[dict[str, Any]]:
    script_args: list[str] = []
    if os.path.isdir(NSE_SCRIPT_DIR):
        scripts = [
            os.path.join(NSE_SCRIPT_DIR, name)
            for name in sorted(os.listdir(NSE_SCRIPT_DIR))
            if name.endswith(".nse")
        ]
        if scripts:
            script_args = ["--script", ",".join(scripts)]

    port_arg = ",".join(str(port) for port in open_ports) if open_ports else None
    command = ["nmap", "-sV", "-T3", "--open", *script_args]
    if port_arg:
        command.extend(["-p", port_arg])
    command.append(ip)

    try:
        proc = nmap_runner(command)
    except (subprocess.TimeoutExpired, OSError):
        return []

    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0 and not output:
        return []

    findings: list[dict[str, Any]] = []
    if ip in output:
        findings.append(
            {
                "ip": ip,
                "source": "nmap-nse",
                "severity": "info",
                "title": "Nmap service scan completed",
                "finding_id": f"nmap-scan:{ip}",
                "details": {
                    "output_excerpt": output[:500],
                    "ports_scanned": open_ports,
                },
            },
        )
    return findings


def _run_iot_probes(targets: list[str]) -> list[dict[str, Any]]:
    if not os.path.isdir(IOT_PROBE_DIR):
        return []

    findings: list[dict[str, Any]] = []
    for ip in targets:
        probe_script = os.path.join(IOT_PROBE_DIR, "probe.py")
        if not os.path.isfile(probe_script):
            continue
        try:
            proc = subprocess.run(
                ["python3", probe_script, ip],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        if proc.returncode != 0:
            continue
        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            continue
        for item in payload.get("findings", []):
            findings.append(
                {
                    "ip": ip,
                    "source": "iot-probes",
                    "severity": str(item.get("severity", "info")),
                    "title": str(item.get("title", "IoT probe finding")),
                    "finding_id": str(item.get("finding_id", f"iot:{ip}")),
                    "details": dict(item.get("details") or {}),
                },
            )
    return findings


def _run_http_fingerprints(ip: str, open_ports: list[int]) -> list[dict[str, Any]]:
    web_ports = [port for port in open_ports if port not in NON_HTTP_PORTS]
    if not web_ports:
        web_ports = list(COMMON_WEB_PORTS)

    findings: list[dict[str, Any]] = []
    for port in sorted(set(web_ports)):
        if port in HTTPS_PORTS:
            url = f"https://{ip}:{port}/"
        elif port == 80:
            url = f"http://{ip}/"
        else:
            url = f"http://{ip}:{port}/"
        try:
            proc = subprocess.run(
                [
                    "curl",
                    "-fsSL",
                    "--max-time",
                    "15",
                    "-k",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        if proc.returncode != 0:
            continue
        body = proc.stdout or ""
        if "OWASP Juice Shop" in body:
            findings.append(
                {
                    "ip": ip,
                    "source": "http-probe",
                    "severity": "info",
                    "title": "OWASP Juice Shop detected",
                    "finding_id": f"http-probe:juice-shop:{ip}:{port}",
                    "details": {"url": url, "port": port},
                },
            )
    return findings


def _build_web_base_url(ip: str, port: int) -> str:
    if port in HTTPS_PORTS:
        return f"https://{ip}:{port}"
    if port == 80:
        return f"http://{ip}"
    return f"http://{ip}:{port}"


def _curl_request(
    method: str,
    url: str,
    *,
    timeout_seconds: int = 15,
) -> tuple[int, dict[str, str], str]:
    body_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False) as body_file:
            body_path = body_file.name

        command = [
            "curl",
            "-sS",
            "--max-time",
            str(timeout_seconds),
            "-k",
            "-X",
            method,
            "-D",
            "-",
            "-o",
            body_path,
            url,
        ]
        if method == "POST":
            command.extend(
                [
                    "-H",
                    "Content-Type: application/json",
                    "--data",
                    "{}",
                ],
            )
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 5,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return 0, {}, ""

    status_code = 0
    headers: dict[str, str] = {}
    header_section = proc.stdout or ""
    for line in header_section.splitlines():
        if line.upper().startswith("HTTP/"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                status_code = int(parts[1])
            continue
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()

    body = ""
    if body_path and os.path.isfile(body_path):
        try:
            with open(body_path, encoding="utf-8", errors="replace") as handle:
                body = handle.read(4096)
        except OSError:
            body = ""
        try:
            os.remove(body_path)
        except OSError:
            pass

    return status_code, headers, body


def _run_web_security_probes(
    ip: str,
    open_ports: list[int],
    http_findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    web_ports = [port for port in open_ports if port not in NON_HTTP_PORTS]
    if not web_ports:
        return []

    juice_shop_detected = any(
        finding.get("title") == "OWASP Juice Shop detected" for finding in http_findings
    )
    findings: list[dict[str, Any]] = []

    for port in sorted(set(web_ports)):
        base_url = _build_web_base_url(ip, port)
        status_code, headers, _body = _curl_request("GET", f"{base_url}/")
        if status_code <= 0:
            continue

        for header_name, severity, title in SECURITY_HEADERS:
            if header_name in headers:
                continue
            findings.append(
                {
                    "ip": ip,
                    "source": "web-audit",
                    "severity": severity,
                    "title": title,
                    "finding_id": f"web-audit:missing-header:{header_name}:{ip}:{port}",
                    "details": {
                        "url": f"{base_url}/",
                        "port": port,
                        "header": header_name,
                    },
                },
            )

        path_checks = list(EXPOSED_PATH_CHECKS)
        if not juice_shop_detected:
            path_checks = [
                check
                for check in path_checks
                if check[1] not in {"/api/Challenges", "/rest/user/login", "/ftp/"}
            ]

        for method, path, severity, title in path_checks:
            path_status, _path_headers, path_body = _curl_request(
                method,
                f"{base_url}{path}",
            )
            if path_status <= 0:
                continue
            if path_status >= 400:
                continue
            if path == "/ftp/" and "Index of" not in path_body and "directory" not in path_body.lower():
                continue
            if path == "/api/Challenges" and "data" not in path_body.lower():
                continue

            findings.append(
                {
                    "ip": ip,
                    "source": "web-audit",
                    "severity": severity,
                    "title": title,
                    "finding_id": f"web-audit:path:{path}:{ip}:{port}",
                    "details": {
                        "url": f"{base_url}{path}",
                        "port": port,
                        "method": method,
                        "status_code": path_status,
                    },
                },
            )

    return findings
