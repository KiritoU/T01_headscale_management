from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import ScopeType
from accounts.permissions import (
    DenyViewerOnWorkersGateways,
    IsAuthenticatedHuman,
    ScopedResourceAccess,
)
from agents.authentication import AgentBearerAuthentication
from agents.models import Agent, AgentCommand, AgentModule, CommandState
from agents.permissions import IsAgentOwner
from agents.serializers import (
    AgentCommandAckSerializer,
    AgentCommandEnqueueSerializer,
    AgentCommandResponseSerializer,
    AgentHeartbeatSerializer,
    AgentRegisterSerializer,
)
from agents.services import ack_command, dispatch_commands
from agents.metrics_service import record_resource_sample
from core.request_ip import get_client_ip
from workers.tenant_services import sync_tenant_from_acked_command
from core.responses import api_envelope
from gateways.models import Gateway, GatewayStatus
from workers.models import Worker, WorkerStatus


class AgentRegisterView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        allow_admin_override = bool(
            getattr(request.user, "is_authenticated", False)
            and getattr(request.user, "is_admin", False)
        )
        serializer = AgentRegisterSerializer(
            data=request.data,
            context={"allow_admin_override": allow_admin_override},
        )
        serializer.is_valid(raise_exception=True)
        agent, token = serializer.save()
        return Response(
            {
                "agent_id": str(agent.id),
                "token": token,
                "poll_interval_seconds": agent.poll_interval_seconds,
            },
            status=status.HTTP_201_CREATED,
        )


class AgentHeartbeatView(APIView):
    authentication_classes = [AgentBearerAuthentication]
    permission_classes = [IsAgentOwner]

    def post(self, request: Request, agent_id: str) -> Response:
        agent = request.user
        serializer = AgentHeartbeatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        now = timezone.now()
        updates: dict = {"last_seen_at": now}
        if "tenant_inventory" in data:
            updates["tenant_inventory"] = data["tenant_inventory"]
        Agent.objects.filter(id=agent.id).update(**updates)

        client_ip = get_client_ip(request)
        worker_updates: dict[str, object] = {
            "last_heartbeat_at": now,
            "status": WorkerStatus.ONLINE,
        }
        if "docker_reachable" in data:
            worker_updates["docker_reachable"] = data["docker_reachable"]
        if client_ip:
            worker_updates["public_ip"] = client_ip
        Worker.objects.filter(agent_id=agent.id).update(**worker_updates)

        Gateway.objects.filter(agent_id=agent.id).update(
            last_heartbeat_at=now,
            status=GatewayStatus.ONLINE,
        )

        for module_data in data.get("installed_modules", []):
            AgentModule.objects.update_or_create(
                agent_id=agent.id,
                name=module_data["module_id"],
                defaults={"installed_at": now},
            )

        if "metrics" in data:
            record_resource_sample(agent, data["metrics"], sampled_at=now)

        return Response({"ok": True})


class AgentPollView(APIView):
    authentication_classes = [AgentBearerAuthentication]
    permission_classes = [IsAgentOwner]

    def get(self, request: Request, agent_id: str) -> Response:
        agent = request.user
        poll_result = dispatch_commands(agent)
        commands = [
            {
                "id": cmd.id,
                "command": cmd.command,
                "payload": cmd.payload,
            }
            for cmd in poll_result.commands
        ]
        return Response({"commands": commands})


class AgentCommandAckView(APIView):
    authentication_classes = [AgentBearerAuthentication]
    permission_classes = [IsAgentOwner]

    def post(self, request: Request, agent_id: str, cmd_id: str) -> Response:
        agent = request.user
        command = get_object_or_404(AgentCommand, id=cmd_id, agent_id=agent.id)

        serializer = AgentCommandAckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        ack_state = CommandState.ACKED if data["state"] == "acked" else CommandState.FAILED
        ack_result = data.get("result", {})
        if command.state in {CommandState.ACKED, CommandState.FAILED}:
            return Response({"ok": True})

        with transaction.atomic():
            ack_command(command, state=ack_state, result=ack_result)
            command.refresh_from_db()
            sync_tenant_from_acked_command(command)
            from gateways.monitoring_service import (
                process_monitor_scan_ack,
                process_vuln_scan_ack,
            )

            process_monitor_scan_ack(command)
            process_vuln_scan_ack(command)

        return Response({"ok": True})


class AgentCommandEnqueueView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticatedHuman, DenyViewerOnWorkersGateways, ScopedResourceAccess]
    scope_type = ScopeType.WORKER

    def get_scope_type(self, obj: Agent):
        if obj.agent_type == "gateway":
            return ScopeType.GATEWAY
        return ScopeType.WORKER

    def get_scope_id(self, obj: Agent):
        if obj.agent_type == "gateway":
            if not hasattr(obj, "gateway"):
                return None
            return obj.gateway.id
        if not hasattr(obj, "worker"):
            return None
        return obj.worker.id

    def post(self, request: Request, agent_id: str) -> Response:
        agent = get_object_or_404(Agent, id=agent_id)
        self.check_object_permissions(request, agent)

        serializer = AgentCommandEnqueueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        command = AgentCommand.objects.create(
            agent=agent,
            command=serializer.validated_data["command"],
            payload=serializer.validated_data.get("payload", {}),
        )

        response_data = AgentCommandResponseSerializer(command).data
        return Response(api_envelope(data=response_data), status=status.HTTP_201_CREATED)
