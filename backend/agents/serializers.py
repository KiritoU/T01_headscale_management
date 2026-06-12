from rest_framework import serializers

from agents.models import AgentCommand, AgentType
from agents.services import create_agent_token
from gateways.models import Gateway
from gateways.services import ENROLL_TOKEN_PREFIX as GATEWAY_ENROLL_TOKEN_PREFIX
from workers.models import Worker
from workers.services import WORKER_ENROLL_TOKEN_PREFIX


class InstalledModuleSerializer(serializers.Serializer):
    module_id = serializers.CharField(max_length=64)
    status = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    version = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")


class AgentRegisterSerializer(serializers.Serializer):
    agent_type = serializers.ChoiceField(choices=AgentType.choices)
    worker_id = serializers.UUIDField(required=False, allow_null=True)
    gateway_id = serializers.UUIDField(required=False, allow_null=True)
    enrollment_token = serializers.CharField(required=False, allow_blank=True, max_length=256)
    hostname = serializers.CharField(required=False, allow_blank=True, max_length=255)
    poll_interval_seconds = serializers.IntegerField(required=False, min_value=5, max_value=300)

    def validate(self, attrs):
        agent_type = attrs["agent_type"]
        worker_id = attrs.get("worker_id")
        gateway_id = attrs.get("gateway_id")
        enrollment_token = (attrs.get("enrollment_token") or "").strip()

        if agent_type == AgentType.WORKER and gateway_id:
            raise serializers.ValidationError("gateway_id is not valid for worker agents.")
        if agent_type == AgentType.GATEWAY and worker_id:
            raise serializers.ValidationError("worker_id is not valid for gateway agents.")
        if agent_type == AgentType.GATEWAY and gateway_id and enrollment_token:
            raise serializers.ValidationError(
                "Provide gateway_id or enrollment_token, not both.",
            )
        if agent_type == AgentType.WORKER and worker_id and enrollment_token:
            raise serializers.ValidationError(
                "Provide worker_id or enrollment_token, not both.",
            )

        if enrollment_token:
            if enrollment_token.startswith(WORKER_ENROLL_TOKEN_PREFIX):
                if agent_type != AgentType.WORKER:
                    raise serializers.ValidationError(
                        "Worker enrollment token requires agent_type worker.",
                    )
            elif enrollment_token.startswith(GATEWAY_ENROLL_TOKEN_PREFIX):
                if agent_type != AgentType.GATEWAY:
                    raise serializers.ValidationError(
                        "Gateway enrollment token requires agent_type gateway.",
                    )
            else:
                raise serializers.ValidationError(
                    "Invalid enrollment token prefix.",
                )

        if worker_id and not Worker.objects.filter(id=worker_id).exists():
            raise serializers.ValidationError({"worker_id": "Worker not found."})
        if gateway_id and not Gateway.objects.filter(id=gateway_id).exists():
            raise serializers.ValidationError({"gateway_id": "Gateway not found."})

        attrs["enrollment_token"] = enrollment_token
        return attrs

    def create(self, validated_data):
        from agents.models import Agent

        enrollment_token = validated_data.pop("enrollment_token", "")
        hostname = validated_data.pop("hostname", "")
        poll_interval_seconds = validated_data.get("poll_interval_seconds", 15)
        worker_id = validated_data.pop("worker_id", None)
        gateway_id = validated_data.pop("gateway_id", None)
        validated_data.pop("poll_interval_seconds", None)

        if enrollment_token:
            if enrollment_token.startswith(WORKER_ENROLL_TOKEN_PREFIX):
                from workers.services import register_worker_from_token

                worker, agent, raw_token = register_worker_from_token(
                    enrollment_token,
                    hostname=hostname,
                )
                if poll_interval_seconds != 15:
                    Agent.objects.filter(pk=agent.pk).update(
                        poll_interval_seconds=poll_interval_seconds,
                    )
                    agent.refresh_from_db()
                return agent, raw_token

            from gateways.services import register_gateway_from_token

            gateway, agent, raw_token = register_gateway_from_token(
                enrollment_token,
                hostname=hostname,
            )
            if poll_interval_seconds != 15:
                Agent.objects.filter(pk=agent.pk).update(
                    poll_interval_seconds=poll_interval_seconds,
                )
                agent.refresh_from_db()
            return agent, raw_token

        creds = create_agent_token()

        agent = Agent.objects.create(
            agent_type=validated_data["agent_type"],
            token_prefix=creds.token_prefix,
            token_hash=creds.token_hash,
            poll_interval_seconds=poll_interval_seconds,
        )

        if worker_id:
            Worker.objects.filter(id=worker_id).update(agent=agent)
        if gateway_id:
            Gateway.objects.filter(id=gateway_id).update(agent=agent)

        return agent, creds.raw_token


class AgentHeartbeatSerializer(serializers.Serializer):
    installed_modules = InstalledModuleSerializer(many=True, required=False, default=list)
    docker_reachable = serializers.BooleanField(required=False, allow_null=True)
    tenant_inventory = serializers.JSONField(required=False)


class AgentCommandEnqueueSerializer(serializers.Serializer):
    command = serializers.CharField(max_length=64)
    payload = serializers.JSONField(required=False, default=dict)


class AgentCommandResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentCommand
        fields = ("id", "command", "payload", "state", "created_at")


class AgentCommandAckSerializer(serializers.Serializer):
    state = serializers.ChoiceField(choices=["acked", "failed"])
    result = serializers.DictField(child=serializers.JSONField(), required=False, default=dict)

    def validate_result(self, value):
        allowed = {
            "exit_code",
            "duration_ms",
            "logs",
            "runtime_status",
            "config_ref",
            "checks",
            "bootstrap",
            "bootstrap_status",
        }
        unknown = set(value) - allowed
        if unknown:
            fields = ", ".join(sorted(unknown))
            raise serializers.ValidationError(f"Unknown result fields: {fields}")
        return value
