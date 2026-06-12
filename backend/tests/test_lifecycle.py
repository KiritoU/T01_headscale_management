import uuid

import pytest
from django.urls import reverse

from agents.models import Agent, AgentCommand, AgentType, CommandState
from lifecycle.deployment import (
    login_server_url,
    tenant_base_domain,
    tenant_download_host,
    tenant_production_mode,
)
from lifecycle.generator import (
    generate_headplane_config,
    generate_headscale_config,
    generate_tenant_config,
    tenant_config_input_from_model,
)
from lifecycle.provision_payload import build_provision_payload
from lifecycle.render import (
    dict_to_yaml,
    resolve_headplane_config_for_worker,
    resolve_headscale_config_for_worker,
)
from lifecycle.scripts import generate_gateway_script, generate_linux_script, generate_script
from lifecycle.stack_generator import (
    assemble_compose_yml,
    generate_traefik_service,
    stack_file_bundle,
    traefik_router_labels,
)
from lifecycle.services import TenantLifecycleError, enqueue_bootstrap_tenant, enqueue_verify_tenant
from tenants.models import BootstrapStatus, Tenant
from workers.models import Worker


@pytest.fixture
def worker(db):
    return Worker.objects.create(name="worker-lifecycle", hostname="lifecycle.vps.example.com")


@pytest.fixture
def worker_agent(worker):
    agent = Agent.objects.create(
        agent_type=AgentType.WORKER,
        token_prefix="agnt_lc1",
        token_hash="a" * 64,
    )
    worker.agent = agent
    worker.save(update_fields=["agent"])
    return agent


@pytest.fixture
def tenant(worker, worker_agent):
    return Tenant.objects.create(
        slug="team-1",
        headscale_host="headscale-team-1.example.com",
        headplane_host="headplane-team-1.example.com",
        db_name="hs_team_1",
        worker=worker,
        desired_config={"dns": {"magic_dns_base": "tailnet-team-1.example.com"}},
    )


@pytest.fixture
def production_tenant(worker, worker_agent):
    return Tenant.objects.create(
        slug="prod-1",
        headscale_host="headscale-prod-1.example.com",
        headplane_host="headplane-prod-1.example.com",
        db_name="hs_prod_1",
        worker=worker,
        desired_config={
            "production": True,
            "base_domain": "example.com",
            "download_host": "download.example.com",
            "dns": {"magic_dns_base": "tailnet-prod-1.example.com"},
        },
    )


class TestDeployment:
    def test_tenant_production_mode_defaults_false(self):
        assert tenant_production_mode(None) is False
        assert tenant_production_mode({}) is False
        assert tenant_production_mode({"production": True}) is True

    def test_tenant_base_domain_from_desired_config(self):
        assert tenant_base_domain(
            {"base_domain": "custom.example.com"},
            headscale_host="headscale-team-1.example.com",
        ) == "custom.example.com"

    def test_tenant_base_domain_derived_from_headscale_host(self):
        assert tenant_base_domain(
            None,
            headscale_host="headscale-team-1.example.com",
        ) == "example.com"

    def test_tenant_download_host(self):
        assert tenant_download_host(
            {"download_host": "files.example.com"},
            base_domain="example.com",
        ) == "files.example.com"
        assert tenant_download_host(None, base_domain="example.com") == "download.example.com"

    def test_login_server_url_dev_vs_production(self):
        assert login_server_url("headscale-team-1.example.com", production=False) == (
            "http://headscale-team-1.example.com"
        )
        assert login_server_url("headscale-team-1.example.com", production=True) == (
            "https://headscale-team-1.example.com"
        )


class TestStackGenerator:
    def test_traefik_router_labels_dev_uses_web_entrypoint(self):
        labels = traefik_router_labels(
            router_name="headscale-team-1",
            host="headscale-team-1.example.com",
            production=False,
            service_port=8080,
        )

        assert "traefik.http.routers.headscale-team-1.entrypoints=web" in labels
        assert not any("websecure" in label for label in labels)
        assert not any("tls.certresolver" in label for label in labels)

    def test_traefik_router_labels_production_uses_websecure(self):
        labels = traefik_router_labels(
            router_name="headscale-team-1",
            host="headscale-team-1.example.com",
            production=True,
            service_port=8080,
        )

        assert "traefik.http.routers.headscale-team-1.entrypoints=websecure" in labels
        assert "traefik.http.routers.headscale-team-1.tls.certresolver=letsencrypt" in labels

    def test_generate_traefik_service_dev_vs_production(self):
        dev = generate_traefik_service(production=False)
        prod = generate_traefik_service(production=True)

        assert "entrypoints.web.address=:80" in dev
        assert "443:443" not in dev
        assert "env_file" not in dev

        assert "entrypoints.websecure.address=:443" in prod
        assert "443:443" in prod
        assert "env_file:" in prod
        assert "./traefik/acme:/acme" in prod

    def test_assemble_compose_yml_includes_shared_and_tenant_blocks(self):
        tenant_block = "  headscale-team-1:\n    image: headscale/headscale:latest"
        compose = assemble_compose_yml(
            production=False,
            download_host="download.example.com",
            tenant_service_blocks=[tenant_block],
        )

        assert compose.startswith("services:")
        assert "traefik:" in compose
        assert "postgres:" in compose
        assert "pgbouncer:" in compose
        assert "scripts:" in compose
        assert tenant_block in compose
        assert "entrypoints=web" in compose

    def test_stack_file_bundle_contains_expected_paths(self):
        bundle = stack_file_bundle(
            production=False,
            download_host="download.example.com",
            database_lines={"hs_team_1": "host=postgres port=5432 dbname=hs_team_1"},
            postgres_user="headscale",
            postgres_password="secret-postgres",
            pgbouncer_user="pgbouncer",
            pgbouncer_password="secret-pgbouncer",
            database_names_for_init=["hs_team_1"],
            tenant_service_blocks=["  headscale-team-1:\n    image: headscale/headscale:latest"],
        )

        assert set(bundle) == {
            "ACL.json",
            "nginx.conf",
            "pgbouncer/pgbouncer.ini",
            "pgbouncer/userlist.txt",
            "postgres/init/00-init.sql",
            "compose.yml",
        }
        assert "hs_team_1 = host=postgres port=5432 dbname=hs_team_1" in bundle["pgbouncer/pgbouncer.ini"]


class TestRender:
    def test_resolve_headscale_config_for_worker(self):
        config = {
            "database": {
                "postgres": {
                    "pass_ref": "env:POSTGRES_PASSWORD",
                    "name": "hs_team_1",
                },
            },
        }

        resolved = resolve_headscale_config_for_worker(config, postgres_password="resolved-pass")

        assert resolved["database"]["postgres"]["pass"] == "resolved-pass"
        assert "pass_ref" not in resolved["database"]["postgres"]

    def test_resolve_headplane_config_for_worker(self):
        config = {
            "server": {"cookie_secret_ref": "secrets://cookie"},
            "auth": {"local_admin": {"password_ref": "secrets://password"}},
        }

        resolved = resolve_headplane_config_for_worker(
            config,
            cookie_secret="cookie-value",
            admin_password="admin-value",
        )

        assert resolved["server"]["cookie_secret"] == "cookie-value"
        assert resolved["auth"]["local_admin"]["password"] == "admin-value"
        assert "cookie_secret_ref" not in resolved["server"]
        assert "password_ref" not in resolved["auth"]["local_admin"]

    def test_dict_to_yaml(self):
        rendered = dict_to_yaml({"server_url": "http://example.com", "listen_addr": "0.0.0.0:8080"})

        assert "server_url: http://example.com" in rendered
        assert "listen_addr: 0.0.0.0:8080" in rendered


class TestProvisionPayload:
    def test_build_provision_payload_includes_inline_configs(self, tenant):
        payload = build_provision_payload(tenant)

        assert payload["tenant_slug"] == "team-1"
        assert payload["production"] is False
        assert payload["login_server"] == "http://headscale-team-1.example.com"
        assert isinstance(payload["headscale_config"], dict)
        assert isinstance(payload["headplane_config"], dict)
        assert isinstance(payload["compose_snippet"], str)
        assert "headscale-team-1:" in payload["compose_snippet"]
        assert payload["client_scripts"]["linux.sh"]
        assert payload["client_scripts"]["gateway.sh"]

    def test_build_provision_payload_production_mode(self, production_tenant):
        payload = build_provision_payload(production_tenant)

        assert payload["production"] is True
        assert payload["login_server"] == "https://headscale-prod-1.example.com"
        assert "entrypoints=websecure" in payload["compose_snippet"]


class TestGenerator:
    def test_tenant_config_input_from_model(self, tenant):
        config_input = tenant_config_input_from_model(tenant)

        assert config_input.slug == "team-1"
        assert config_input.login_server == "http://headscale-team-1.example.com"
        assert config_input.production is False
        assert config_input.magic_dns_base == "tailnet-team-1.example.com"
        assert config_input.headscale_container == "headscale-team-1"

    def test_tenant_config_input_production_mode(self, production_tenant):
        config_input = tenant_config_input_from_model(production_tenant)

        assert config_input.production is True
        assert config_input.login_server == "https://headscale-prod-1.example.com"
        assert config_input.download_host == "download.example.com"

    def test_headscale_config_uses_refs_not_raw_secrets(self, tenant):
        config_input = tenant_config_input_from_model(tenant)
        headscale = generate_headscale_config(config_input)

        assert headscale["server_url"] == "http://headscale-team-1.example.com"
        assert headscale["database"]["postgres"]["name"] == "hs_team_1"
        assert headscale["database"]["postgres"]["pass_ref"] == "env:POSTGRES_PASSWORD"
        assert "pass" not in headscale["database"]["postgres"]

    def test_headplane_config_uses_secret_refs(self, tenant):
        config_input = tenant_config_input_from_model(tenant)
        headplane = generate_headplane_config(config_input)

        assert headplane["server"]["cookie_secret_ref"] == "secrets://tenants/team-1/headplane/cookie_secret"
        assert headplane["auth"]["local_admin"]["password_ref"] == (
            "secrets://tenants/team-1/headplane/admin_password"
        )
        assert "password" not in headplane["auth"]["local_admin"]

    def test_generate_tenant_config_includes_compose_snippet(self, tenant):
        config = generate_tenant_config(tenant)

        assert config["slug"] == "team-1"
        assert config["production"] is False
        assert "headscale-team-1:" in config["compose_snippet"]
        assert "headplane-team-1:" in config["compose_snippet"]
        assert "entrypoints=web" in config["compose_snippet"]
        assert "headscale" in config
        assert "headplane" in config

    def test_generate_tenant_config_production_traefik_labels(self, production_tenant):
        config = generate_tenant_config(production_tenant)

        assert config["production"] is True
        assert config["login_server"] == "https://headscale-prod-1.example.com"
        assert "entrypoints=websecure" in config["compose_snippet"]
        assert "tls.certresolver=letsencrypt" in config["compose_snippet"]


class TestScripts:
    def test_linux_script_substitutes_login_server(self):
        script = generate_linux_script(login_server="https://headscale-team-1.example.com")

        assert 'LOGIN_SERVER="https://headscale-team-1.example.com"' in script
        assert "--accept-routes" in script

    def test_gateway_script_substitutes_login_server(self):
        script = generate_gateway_script(login_server="https://headscale-team-1.example.com")

        assert 'LOGIN_SERVER="https://headscale-team-1.example.com"' in script
        assert "--advertise-routes" in script

    def test_generate_script_rejects_unknown_name(self):
        with pytest.raises(ValueError, match="Unsupported script"):
            generate_script("window.ps1", login_server="https://example.com")


@pytest.mark.django_db
class TestLifecycleServices:
    def test_enqueue_verify_tenant(self, tenant, worker_agent):
        command = enqueue_verify_tenant(tenant)

        assert command.command == "verify_tenant"
        stored = AgentCommand.objects.get(id=command.id)
        assert stored.agent_id == worker_agent.id
        assert stored.state == CommandState.PENDING
        assert stored.payload["tenant_slug"] == "team-1"
        assert stored.payload["headscale_host"] == "headscale-team-1.example.com"

    def test_enqueue_bootstrap_sets_output_ref(self, tenant, worker_agent):
        command = enqueue_bootstrap_tenant(tenant)

        assert command.command == "bootstrap_tenant"
        tenant.refresh_from_db()
        assert tenant.bootstrap_status == BootstrapStatus.PROVISIONING
        assert tenant.bootstrap_output_ref == (
            f"worker-output://{tenant.worker_id}/tenants/team-1/bootstrap"
        )

        stored = AgentCommand.objects.get(id=command.id)
        assert stored.payload["output_ref"] == tenant.bootstrap_output_ref

    def test_enqueue_fails_without_worker(self, db):
        tenant = Tenant.objects.create(
            slug="orphan",
            headscale_host="hs.example.com",
            headplane_host="hp.example.com",
            db_name="hs_orphan",
        )

        with pytest.raises(TenantLifecycleError, match="no assigned worker"):
            enqueue_verify_tenant(tenant)

    def test_enqueue_fails_without_agent(self, worker):
        tenant = Tenant.objects.create(
            slug="no-agent",
            headscale_host="hs.example.com",
            headplane_host="hp.example.com",
            db_name="hs_no_agent",
            worker=worker,
        )

        with pytest.raises(TenantLifecycleError, match="no registered agent"):
            enqueue_bootstrap_tenant(tenant)

    def test_bootstrap_skips_when_already_bootstrapped(self, tenant, worker_agent):
        output_ref = f"worker-output://{tenant.worker_id}/tenants/team-1/bootstrap"
        Tenant.objects.filter(pk=tenant.pk).update(
            bootstrap_status=BootstrapStatus.BOOTSTRAPPED,
            bootstrap_output_ref=output_ref,
        )
        tenant.refresh_from_db()

        result = enqueue_bootstrap_tenant(tenant)

        assert result.skipped is True
        assert result.id is None
        assert result.bootstrap_output_ref == output_ref
        assert result.bootstrap_status == BootstrapStatus.BOOTSTRAPPED
        bootstrap_cmds = AgentCommand.objects.filter(
            agent=worker_agent,
            command="bootstrap_tenant",
        )
        assert bootstrap_cmds.count() == 0

    def test_bootstrap_skips_duplicate_pending_command(self, tenant, worker_agent):
        first = enqueue_bootstrap_tenant(tenant)
        second = enqueue_bootstrap_tenant(tenant)

        assert second.skipped is True
        assert second.id == first.id
        bootstrap_cmds = AgentCommand.objects.filter(
            agent=worker_agent,
            command="bootstrap_tenant",
        )
        assert bootstrap_cmds.count() == 1

    def test_verify_skips_duplicate_pending_command(self, tenant, worker_agent):
        first = enqueue_verify_tenant(tenant)
        second = enqueue_verify_tenant(tenant)

        assert second.skipped is True
        assert second.id == first.id
        assert AgentCommand.objects.filter(agent=worker_agent, command="verify_tenant").count() == 1


@pytest.mark.django_db
class TestLifecycleApi:
    def test_get_tenant_config(self, client, tenant):
        response = client.get(reverse("tenant-config", kwargs={"tenant_id": tenant.id}))

        assert response.status_code == 200
        data = response.json()
        assert data["slug"] == "team-1"
        assert data["headscale"]["policy"]["mode"] == "database"
        assert "compose_snippet" in data

    def test_get_linux_script(self, client, tenant):
        response = client.get(
            reverse("tenant-script", kwargs={"tenant_id": tenant.id, "name": "linux.sh"})
        )

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/x-shellscript")
        assert b'LOGIN_SERVER="http://headscale-team-1.example.com"' in response.content

    def test_get_gateway_script(self, client, tenant):
        response = client.get(
            reverse("tenant-script", kwargs={"tenant_id": tenant.id, "name": "gateway.sh"})
        )

        assert response.status_code == 200
        assert b"--advertise-routes" in response.content

    def test_get_unknown_script_returns_envelope(self, client, tenant):
        response = client.get(
            reverse("tenant-script", kwargs={"tenant_id": tenant.id, "name": "window.ps1"})
        )

        assert response.status_code == 404
        body = response.json()
        assert body["success"] is False
        assert "Unsupported script" in body["error"]

    def test_post_verify_enqueues_command(self, client, tenant, worker_agent):
        response = client.post(reverse("tenant-verify", kwargs={"tenant_id": tenant.id}))

        assert response.status_code == 202
        body = response.json()
        assert body["success"] is True
        assert body["data"]["command"] == "verify_tenant"
        assert AgentCommand.objects.filter(
            id=body["data"]["command_id"],
            command="verify_tenant",
            state=CommandState.PENDING,
        ).exists()

    def test_post_bootstrap_enqueues_and_tracks_ref(self, client, tenant, worker_agent):
        response = client.post(reverse("tenant-bootstrap", kwargs={"tenant_id": tenant.id}))

        assert response.status_code == 202
        body = response.json()
        assert body["success"] is True
        assert body["data"]["bootstrap_status"] == BootstrapStatus.PROVISIONING
        assert body["data"]["bootstrap_output_ref"].startswith("worker-output://")

        tenant.refresh_from_db()
        assert tenant.bootstrap_output_ref == body["data"]["bootstrap_output_ref"]

    def test_post_verify_without_worker_returns_envelope(self, client, db):
        tenant = Tenant.objects.create(
            slug="solo",
            headscale_host="hs.example.com",
            headplane_host="hp.example.com",
            db_name="hs_solo",
        )
        response = client.post(reverse("tenant-verify", kwargs={"tenant_id": tenant.id}))

        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert "worker" in body["error"].lower()

    def test_config_not_found(self, client):
        response = client.get(reverse("tenant-config", kwargs={"tenant_id": uuid.uuid4()}))

        assert response.status_code == 404
