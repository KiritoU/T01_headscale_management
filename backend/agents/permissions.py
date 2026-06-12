from rest_framework.permissions import BasePermission


class IsAgentOwner(BasePermission):
    """URL ``agent_id`` must match the authenticated agent."""

    def has_permission(self, request, view) -> bool:
        agent = getattr(request, "user", None)
        if agent is None or not hasattr(agent, "id"):
            return False

        url_agent_id = view.kwargs.get("agent_id")
        if url_agent_id is None:
            return False

        return str(agent.id) == str(url_agent_id)
