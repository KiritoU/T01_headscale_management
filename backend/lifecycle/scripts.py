from __future__ import annotations

import re
from pathlib import Path

SUPPORTED_SCRIPT_NAMES = frozenset({"linux.sh", "gateway.sh", "window.ps1"})

_TEMPLATES_DIR = Path(__file__).parent / "templates" / "client-setup"


def _load_template(name: str) -> str:
    return (_TEMPLATES_DIR / name).read_text(encoding="utf-8")


def _substitute_login_server(
    content: str,
    login_server: str,
    *,
    powershell: bool = False,
) -> str:
    if powershell:
        return re.sub(
            r'^\$LOGIN_SERVER = ".*"',
            f'$LOGIN_SERVER = "{login_server}"',
            content,
            count=1,
            flags=re.MULTILINE,
        )
    return re.sub(
        r'^LOGIN_SERVER=".*"',
        f'LOGIN_SERVER="{login_server}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )


def generate_linux_script(*, login_server: str) -> str:
    return _substitute_login_server(_load_template("linux.sh"), login_server)


def generate_gateway_script(*, login_server: str) -> str:
    return _substitute_login_server(_load_template("gateway.sh"), login_server)


def generate_window_script(*, login_server: str) -> str:
    return _substitute_login_server(
        _load_template("window.ps1"),
        login_server,
        powershell=True,
    )


def generate_script(name: str, *, login_server: str) -> str:
    if name == "linux.sh":
        return generate_linux_script(login_server=login_server)
    if name == "gateway.sh":
        return generate_gateway_script(login_server=login_server)
    if name == "window.ps1":
        return generate_window_script(login_server=login_server)
    msg = f"Unsupported script name: {name}"
    raise ValueError(msg)
