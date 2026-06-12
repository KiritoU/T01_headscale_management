from rest_framework import serializers

from workers.models import Worker, WorkerStatus


class WorkerEnrollmentTokenCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128)
    expires_in_minutes = serializers.IntegerField(
        required=False,
        default=60,
        min_value=1,
        max_value=10080,
    )


class WorkerSerializer(serializers.ModelSerializer):
    installed_modules = serializers.SerializerMethodField()

    class Meta:
        model = Worker
        fields = (
            "id",
            "name",
            "hostname",
            "status",
            "credential_ref",
            "docker_reachable",
            "last_heartbeat_at",
            "installed_modules",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at", "last_heartbeat_at")

    def get_installed_modules(self, worker: Worker) -> list[str]:
        if worker.agent_id is None:
            return []
        return list(
            worker.agent.modules.order_by("name").values_list("name", flat=True),
        )

    def validate_status(self, value):
        if value not in WorkerStatus.values:
            raise serializers.ValidationError(f"Invalid status: {value}")
        return value


class WorkerCommandSerializer(serializers.Serializer):
    command = serializers.ChoiceField(
        choices=[
            "install_module",
            "shutdown",
            "verify_tenant",
            "bootstrap_tenant",
            "provision_tenant",
            "start_tenant",
            "stop_tenant",
        ],
    )
    payload = serializers.JSONField(required=False, default=dict)
