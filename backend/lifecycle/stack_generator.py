from __future__ import annotations

from typing import Any

from lifecycle.identifiers import escape_sql_literal

DEFAULT_ACL_JSON = """{
  "groups": {
    "group:gateway": [],
    "group:workspace": []
  },
  "tagOwners": {
    "tag:gateway": ["group:gateway"],
    "tag:workspace": ["group:workspace"]
  },
  "autoApprovers": {
    "routes": {
      "192.168.0.0/16": ["tag:gateway"]
    }
  },
  "acls": [
    {
      "action": "accept",
      "src": ["*"],
      "dst": ["*:*"]
    }
  ]
}
"""

NGINX_CONF = """server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    charset utf-8;

    autoindex on;
    autoindex_exact_size off;
    autoindex_localtime on;

    location ~ \\.(sh|ps1)$ {
        default_type text/plain;
        add_header Content-Disposition inline always;
    }
}
"""

PGBOUNCER_INI_HEADER = """[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = md5
auth_file = /etc/pgbouncer/userlist.txt

pool_mode = transaction
max_client_conn = 5000
default_pool_size = 20
reserve_pool_size = 5
reserve_pool_timeout = 5

ignore_startup_parameters = extra_float_digits

admin_users = pgbouncer
stats_users = pgbouncer

log_connections = 0
log_disconnections = 0
verbose = 0

[databases]
"""


CONTROL_PLANE_EDGE_NETWORK = "control_plane"


def compose_networks_block(*, shared_edge_traefik: bool, network_name: str) -> str:
    if not shared_edge_traefik:
        return ""
    return f"""
networks:
  {CONTROL_PLANE_EDGE_NETWORK}:
    external: true
    name: {network_name}
"""


def service_edge_networks_block(*, shared_edge_traefik: bool) -> str:
    if not shared_edge_traefik:
        return ""
    return (
        f"    networks:\n"
        f"      - default\n"
        f"      - {CONTROL_PLANE_EDGE_NETWORK}\n"
    )


def traefik_router_labels(
    *,
    router_name: str,
    host: str,
    production: bool,
    service_port: int,
    middlewares: tuple[str, ...] = (),
    docker_network: str = "",
) -> list[str]:
    labels = [
        "traefik.enable=true",
        f"traefik.http.routers.{router_name}.rule=Host(`{host}`)",
        f"traefik.http.services.{router_name}.loadbalancer.server.port={service_port}",
    ]
    # When a container is attached to multiple Docker networks (shared edge mode
    # joins both the worker stack network and the control plane network), Traefik
    # otherwise picks a network at random and may select one it cannot reach,
    # causing requests to hang. Pin the network explicitly.
    if docker_network:
        labels.append(f"traefik.docker.network={docker_network}")
    entrypoint = "websecure" if production else "web"
    labels.append(f"traefik.http.routers.{router_name}.entrypoints={entrypoint}")
    if production:
        labels.append(f"traefik.http.routers.{router_name}.tls.certresolver=letsencrypt")
    if middlewares:
        labels.append(
            f"traefik.http.routers.{router_name}.middlewares={','.join(middlewares)}",
        )
    return labels


def generate_traefik_service(*, production: bool) -> str:
    command_lines = [
        '      - "--entrypoints.web.address=:80"',
        '      - "--providers.docker=true"',
        '      - "--providers.docker.exposedByDefault=false"',
        '      - "--log.level=INFO"',
        '      - "--api.dashboard=true"',
        '      - "--api.insecure=true"',
    ]
    ports = ['      - "80:80"']

    if production:
        command_lines.extend(
            [
                '      - "--entrypoints.websecure.address=:443"',
                '      - "--certificatesresolvers.letsencrypt.acme.email=${ACME_EMAIL}"',
                '      - "--certificatesresolvers.letsencrypt.acme.storage=/acme/acme.json"',
                '      - "--certificatesresolvers.letsencrypt.acme.dnschallenge=true"',
                '      - "--certificatesresolvers.letsencrypt.acme.dnschallenge.provider=cloudflare"',
                '      - "--certificatesresolvers.letsencrypt.acme.dnschallenge.delaybeforecheck=10"',
            ],
        )
        ports.extend(['      - "443:443"', '      - "8080:8080"'])
    else:
        ports.append('      - "8080:8080"')

    command_block = "\n".join(command_lines)
    ports_block = "\n".join(ports)
    env_file = "    env_file:\n      - ./.env" if production else ""
    acme_volume = (
        "\n      - ./traefik/acme:/acme"
        if production
        else ""
    )

    return f"""  traefik:
    image: traefik:v3.6.2
    container_name: traefik
    restart: unless-stopped
    command:
{command_block}
{env_file}
    ports:
{ports_block}
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro{acme_volume}
"""


def generate_scripts_service(
    *,
    production: bool,
    download_host: str,
    shared_edge_traefik: bool = False,
    shared_edge_docker_network: str = "",
) -> str:
    labels = traefik_router_labels(
        router_name="scripts",
        host=download_host,
        production=production,
        service_port=80,
        docker_network=shared_edge_docker_network if shared_edge_traefik else "",
    )
    label_lines = "\n".join(f'      - "{label}"' for label in labels)
    networks_block = service_edge_networks_block(shared_edge_traefik=shared_edge_traefik)
    return f"""  scripts:
    image: nginx:alpine
    container_name: scripts
    restart: unless-stopped
    volumes:
      - ./scripts-root:/usr/share/nginx/html:ro
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    labels:
{label_lines}
{networks_block}"""


def generate_postgres_service() -> str:
    return """  postgres:
    image: postgres:16-alpine
    container_name: postgres
    restart: unless-stopped
    environment:
      POSTGRES_PASSWORD: "${POSTGRES_PASSWORD}"
      POSTGRES_USER: "postgres"
      POSTGRES_DB: "postgres"
    volumes:
      - ./postgres/data:/var/lib/postgresql/data
      - ./postgres/init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 3s
      retries: 30
"""


def generate_pgbouncer_service() -> str:
    return """  pgbouncer:
    image: edoburu/pgbouncer:latest
    container_name: pgbouncer
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DB_USER: "${PGBOUNCER_USER}"
      DB_PASSWORD: "${PGBOUNCER_PASSWORD}"
    volumes:
      - ./pgbouncer/pgbouncer.ini:/etc/pgbouncer/pgbouncer.ini:ro
      - ./pgbouncer/userlist.txt:/etc/pgbouncer/userlist.txt:ro
    ports:
      - "6432:6432"
"""


def generate_pgbouncer_ini(database_lines: dict[str, str]) -> str:
    lines = [PGBOUNCER_INI_HEADER.rstrip()]
    for db_name in sorted(database_lines):
        lines.append(f"{db_name} = {database_lines[db_name]}")
    lines.append("")
    return "\n".join(lines)


def generate_pgbouncer_userlist(
    *,
    postgres_user: str,
    postgres_password: str,
    pgbouncer_user: str,
    pgbouncer_password: str,
) -> str:
    return (
        f'"{postgres_user}" "{postgres_password}"\n'
        f'"{pgbouncer_user}" "{pgbouncer_password}"\n'
    )


def generate_postgres_init_sql(
    *,
    postgres_user: str,
    postgres_password: str,
    database_names: list[str],
) -> str:
    escaped_password = escape_sql_literal(postgres_password)
    lines = [
        f"CREATE USER {postgres_user} WITH PASSWORD '{escaped_password}';",
        f"ALTER USER {postgres_user} CREATEDB;",
        "",
    ]
    for db_name in database_names:
        lines.append(f"CREATE DATABASE {db_name} OWNER {postgres_user};")
    lines.append("")
    return "\n".join(lines)


def generate_stack_env_template(*, production: bool) -> str:
    lines = [
        "POSTGRES_PASSWORD=change-me-postgres",
        "PGBOUNCER_USER=pgbouncer",
        "PGBOUNCER_PASSWORD=change-me-pgbouncer",
        "POSTGRES_APP_USER=headscale",
    ]
    if production:
        lines.extend(
            [
                "ACME_EMAIL=admin@example.com",
                "CF_DNS_API_TOKEN=replace-me",
            ],
        )
    return "\n".join(lines) + "\n"


def assemble_compose_yml(
    *,
    production: bool,
    tenant_service_blocks: list[str],
    shared_edge_traefik: bool = False,
    shared_edge_docker_network: str = "",
) -> str:
    shared = ["services:"]
    if not shared_edge_traefik:
        shared.append(generate_traefik_service(production=production).rstrip())
    shared.extend(
        [
            generate_postgres_service().rstrip(),
            generate_pgbouncer_service().rstrip(),
        ],
    )
    blocks = shared + [block.rstrip() for block in tenant_service_blocks if block.strip()]
    body = "\n\n".join(blocks)
    networks = compose_networks_block(
        shared_edge_traefik=shared_edge_traefik,
        network_name=shared_edge_docker_network,
    )
    return body + networks + "\n"


def stack_file_bundle(
    *,
    production: bool,
    database_lines: dict[str, str],
    postgres_user: str,
    postgres_password: str,
    pgbouncer_user: str,
    pgbouncer_password: str,
    database_names_for_init: list[str],
    tenant_service_blocks: list[str],
    shared_edge_traefik: bool = False,
    shared_edge_docker_network: str = "",
) -> dict[str, str]:
    return {
        "ACL.json": DEFAULT_ACL_JSON,
        "pgbouncer/pgbouncer.ini": generate_pgbouncer_ini(database_lines),
        "pgbouncer/userlist.txt": generate_pgbouncer_userlist(
            postgres_user=postgres_user,
            postgres_password=postgres_password,
            pgbouncer_user=pgbouncer_user,
            pgbouncer_password=pgbouncer_password,
        ),
        "postgres/init/00-init.sql": generate_postgres_init_sql(
            postgres_user=postgres_user,
            postgres_password=postgres_password,
            database_names=database_names_for_init,
        ),
        "compose.yml": assemble_compose_yml(
            production=production,
            tenant_service_blocks=tenant_service_blocks,
            shared_edge_traefik=shared_edge_traefik,
            shared_edge_docker_network=shared_edge_docker_network,
        ),
    }


def pgbouncer_database_line(db_name: str) -> str:
    return f"host=postgres port=5432 dbname={db_name}"
