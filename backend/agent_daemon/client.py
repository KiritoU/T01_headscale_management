from __future__ import annotations

from typing import Any

import httpx


class AgentClient:
    """HTTP client for the control plane agent polling protocol."""

    def __init__(
        self,
        control_plane_url: str,
        token: str,
        *,
        agent_id: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = control_plane_url.rstrip("/")
        self._token = token
        self._agent_id = agent_id
        self._client = http_client or httpx.Client(timeout=30.0)
        self._owns_client = http_client is None

    @property
    def agent_id(self) -> str | None:
        return self._agent_id

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _require_agent_id(self) -> str:
        if self._agent_id is None:
            msg = "agent_id is required; call register() or pass agent_id to AgentClient"
            raise RuntimeError(msg)
        return self._agent_id

    def register(
        self,
        *,
        agent_type: str = "worker",
        name: str,
    ) -> dict[str, Any]:
        response = self._client.post(
            f"{self._base_url}/api/v1/agents/register/",
            json={"agent_type": agent_type, "name": name},
            headers=self._headers(),
        )
        response.raise_for_status()
        data = response.json()
        self._agent_id = data["agent_id"]
        return data

    def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent_id = self._require_agent_id()
        response = self._client.post(
            f"{self._base_url}/api/v1/agents/{agent_id}/heartbeat/",
            json=payload,
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    def poll(self, *, since: str | None = None) -> dict[str, Any]:
        agent_id = self._require_agent_id()
        params: dict[str, str] = {}
        if since is not None:
            params["since"] = since
        response = self._client.get(
            f"{self._base_url}/api/v1/agents/{agent_id}/poll/",
            params=params,
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    def ack(
        self,
        command_id: str,
        *,
        state: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        agent_id = self._require_agent_id()
        response = self._client.post(
            f"{self._base_url}/api/v1/agents/{agent_id}/commands/{command_id}/ack/",
            json={"state": state, "result": result},
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
