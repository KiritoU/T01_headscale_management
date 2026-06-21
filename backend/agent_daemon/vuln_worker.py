from __future__ import annotations

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agent_daemon.client import AgentClient
from agent_daemon.vuln_scan import run_vuln_scan

logger = logging.getLogger(__name__)


class VulnWorkerPool:
    """Background vuln scans — does not block the gateway poll loop."""

    def __init__(
        self,
        client: AgentClient,
        *,
        nmap_runner,
        masscan_runner=None,
        max_workers: int = 4,
    ) -> None:
        self._client = client
        self._nmap_runner = nmap_runner
        self._masscan_runner = masscan_runner
        self._max_workers = max(1, max_workers)
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="vuln-worker",
        )
        self._active_jobs: set[str] = set()
        self._lock = threading.Lock()

    def tick(self) -> None:
        try:
            queue = self._client.get_vuln_queue()
        except Exception:
            logger.exception("failed to fetch vuln queue")
            return

        parallel_workers = int(queue.get("parallel_workers") or self._max_workers)
        targets = list(queue.get("targets") or [])
        if not targets:
            return

        with self._lock:
            available = max(parallel_workers - len(self._active_jobs), 0)
            to_schedule = []
            for item in targets:
                if available <= 0:
                    break
                job_id = str(item.get("job_id", ""))
                ip = str(item.get("ip", "")).strip()
                if not job_id or not ip:
                    continue
                if job_id in self._active_jobs:
                    continue
                self._active_jobs.add(job_id)
                to_schedule.append(item)
                available -= 1

        for item in to_schedule:
            self._executor.submit(self._run_job, item)

    def _run_job(self, item: dict[str, Any]) -> None:
        job_id = str(item["job_id"])
        ip = str(item["ip"])
        modules = list(item.get("modules") or [])
        open_ports = list(item.get("open_ports") or [])
        try:
            body = run_vuln_scan(
                [ip],
                nmap_runner=self._nmap_runner,
                modules=modules,
                open_ports=open_ports,
                masscan_runner=self._masscan_runner,
            )
            self._client.post_vuln_results(
                {
                    "job_id": job_id,
                    "ip": ip,
                    "findings": body.get("findings", []),
                    "completed": True,
                },
            )
        except Exception:
            logger.exception("vuln job failed for %s", ip)
            try:
                self._client.post_vuln_results(
                    {
                        "job_id": job_id,
                        "ip": ip,
                        "findings": [],
                        "completed": True,
                        "error": "vuln scan failed",
                    },
                )
            except Exception:
                logger.exception("failed to report vuln job failure for %s", ip)
        finally:
            with self._lock:
                self._active_jobs.discard(job_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
