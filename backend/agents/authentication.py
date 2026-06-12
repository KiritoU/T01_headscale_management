from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from agents.services import verify_agent_token


class AgentBearerAuthentication(BaseAuthentication):
    """Authenticate agent requests via Bearer token (agnt_ prefix)."""

    keyword = "Bearer"

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            return None

        raw_token = parts[1]
        verified = verify_agent_token(raw_token)
        if verified is None:
            raise AuthenticationFailed("Invalid agent credentials.")

        return (verified.agent, raw_token)
