from django.urls import path

from agents.views import (
    AgentCommandAckView,
    AgentCommandEnqueueView,
    AgentHeartbeatView,
    AgentPollView,
    AgentRegisterView,
)
from agents.monitoring_views import AgentVulnQueueView, AgentVulnResultsView

urlpatterns = [
    path("agents/register/", AgentRegisterView.as_view(), name="agent-register"),
    path("agents/<uuid:agent_id>/heartbeat/", AgentHeartbeatView.as_view(), name="agent-heartbeat"),
    path("agents/<uuid:agent_id>/poll/", AgentPollView.as_view(), name="agent-poll"),
    path(
        "agents/<uuid:agent_id>/commands/<uuid:cmd_id>/ack/",
        AgentCommandAckView.as_view(),
        name="agent-command-ack",
    ),
    path(
        "agents/<uuid:agent_id>/commands/",
        AgentCommandEnqueueView.as_view(),
        name="agent-command-enqueue",
    ),
    path(
        "agents/<uuid:agent_id>/monitoring/vuln-queue/",
        AgentVulnQueueView.as_view(),
        name="agent-vuln-queue",
    ),
    path(
        "agents/<uuid:agent_id>/monitoring/vuln-results/",
        AgentVulnResultsView.as_view(),
        name="agent-vuln-results",
    ),
]
