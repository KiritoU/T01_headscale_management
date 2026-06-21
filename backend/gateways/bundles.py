from __future__ import annotations

import tarfile
from io import BytesIO
from pathlib import Path

from django.http import FileResponse, Http404, HttpRequest

BUNDLE_ROOT = Path(__file__).resolve().parent.parent / "static" / "gateway-modules"

ALLOWED_BUNDLES = {
    "gateway-vuln-nse-pack.tar.gz": "vuln-nse-pack",
    "gateway-iot-probes.tar.gz": "iot-probes",
}


def gateway_module_bundle(request: HttpRequest, bundle_name: str) -> FileResponse:
    if bundle_name not in ALLOWED_BUNDLES:
        raise Http404("Unknown bundle")

    bundle_path = BUNDLE_ROOT / bundle_name
    if not bundle_path.is_file():
        raise Http404("Bundle not found")

    return FileResponse(
        bundle_path.open("rb"),
        as_attachment=True,
        filename=bundle_name,
        content_type="application/gzip",
    )


def ensure_gateway_bundles() -> None:
    """Create minimal gateway module bundles if missing (dev/bootstrap)."""
    BUNDLE_ROOT.mkdir(parents=True, exist_ok=True)

    nse_bundle = BUNDLE_ROOT / "gateway-vuln-nse-pack.tar.gz"
    if not nse_bundle.is_file():
        buffer = BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            content = b'-- placeholder NSE script\n'
            info = tarfile.TarInfo(name="safe-banner.nse")
            info.size = len(content)
            archive.addfile(info, BytesIO(content))
        nse_bundle.write_bytes(buffer.getvalue())

    iot_bundle = BUNDLE_ROOT / "gateway-iot-probes.tar.gz"
    if not iot_bundle.is_file():
        buffer = BytesIO()
        probe_script = (
            b"import json, sys\n"
            b"ip = sys.argv[1] if len(sys.argv) > 1 else ''\n"
            b"print(json.dumps({'findings': []}))\n"
        )
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            info = tarfile.TarInfo(name="probe.py")
            info.size = len(probe_script)
            archive.addfile(info, BytesIO(probe_script))
        iot_bundle.write_bytes(buffer.getvalue())
