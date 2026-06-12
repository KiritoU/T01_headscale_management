from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

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
from workers.tenant_services import sync_tenant_from_acked_command
from core.permissions import DebugOrTestAllowAny
from core.responses import api_envelope
from gateways.models import Gateway, GatewayStatus
from workers.models import Worker, WorkerStatus


class AgentRegisterView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = AgentRegisterSerializer(data=request.data)
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

        if "docker_reachable" in data:
            Worker.objects.filter(agent_id=agent.id).update(
                docker_reachable=data["docker_reachable"],
                last_heartbeat_at=now,
                status=WorkerStatus.ONLINE,
            )
        else:
            Worker.objects.filter(agent_id=agent.id).update(
                last_heartbeat_at=now,
                status=WorkerStatus.ONLINE,
            )

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
        ack_command(command, state=ack_state, result=data.get("result", {}))
        sync_tenant_from_acked_command(command)

        return Response({"ok": True})


class AgentCommandEnqueueView(APIView):
    authentication_classes: list = []
    permission_classes = [DebugOrTestAllowAny]

    def post(self, request: Request, agent_id: str) -> Response:
        agent = get_object_or_404(Agent, id=agent_id)

        serializer = AgentCommandEnqueueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        command = AgentCommand.objects.create(
            agent=agent,
            command=serializer.validated_data["command"],
            payload=serializer.validated_data.get("payload", {}),
        )

        response_data = AgentCommandResponseSerializer(command).data
        return Response(api_envelope(data=response_data), status=status.HTTP_201_CREATED)
