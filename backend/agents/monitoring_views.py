from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from agents.authentication import AgentBearerAuthentication
from agents.models import Agent
from agents.permissions import IsAgentOwner
from gateways.monitoring_service import get_vuln_scan_queue, process_vuln_results_push


class AgentVulnQueueView(APIView):
    authentication_classes = [AgentBearerAuthentication]
    permission_classes = [IsAgentOwner]

    def get(self, request: Request, agent_id: str) -> Response:
        agent = request.user
        if str(agent.id) != str(agent_id):
            agent = get_object_or_404(Agent, id=agent_id)
        return Response(get_vuln_scan_queue(agent))


class AgentVulnResultsView(APIView):
    authentication_classes = [AgentBearerAuthentication]
    permission_classes = [IsAgentOwner]

    def post(self, request: Request, agent_id: str) -> Response:
        agent = request.user
        if str(agent.id) != str(agent_id):
            agent = get_object_or_404(Agent, id=agent_id)
        process_vuln_results_push(agent, request.data)
        return Response({"ok": True})
