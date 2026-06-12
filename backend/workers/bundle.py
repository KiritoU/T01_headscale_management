import io
import tarfile
from pathlib import Path

from django.conf import settings


def _add_package_tree(archive: tarfile.TarFile, package_dir: Path, base_dir: Path) -> None:
    for path in sorted(package_dir.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            archive.add(path, arcname=str(path.relative_to(base_dir)))


def build_agent_daemon_tarball() -> bytes:
    """Pack agent_daemon (+ lifecycle deps) for remote install (curl | bash flow)."""
    base_dir = Path(settings.BASE_DIR)
    packages = (
        base_dir / "agent_daemon",
        base_dir / "lifecycle",
        base_dir / "scripts" / "agent-requirements.txt",
    )
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for package_path in packages:
            if package_path.is_dir():
                _add_package_tree(archive, package_path, base_dir)
            elif package_path.is_file():
                archive.add(package_path, arcname=str(package_path.relative_to(base_dir)))
    buffer.seek(0)
    return buffer.read()
