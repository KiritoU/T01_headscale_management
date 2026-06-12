# Kế hoạch phát triển tạm thời — Headscale Management

> Chi tiết GSD: `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`

**Cập nhật:** 2026-06-08 (polling + modular tailscale/nmap)  
**Trạng thái:** Planning — Phase 1 chưa bắt đầu

---

## Mục tiêu

Xây **control plane** thay thế dần `generate-multi-tenants.sh`, với **gateway agent** quản lý từ xa các máy subnet router.

| Legacy | Mục tiêu |
|--------|---------|
| `gateway.sh` one-shot, prompt thủ công | **Gateway agent** daemon + lệnh từ server |
| Script tải qua Nginx per tenant | `curl -LsSf https://get.{domain}/gateway-agent.sh \| sh` |
| Tags cố định `tag:gateway` | Server gán **custom tags** thêm per gateway |
| Operator tự nhập subnet | Server ra lệnh **scan_network** → chọn CIDR → **tailscale_up** |
| Cài tailscale/nmap lúc setup | **Modules** — server bấm nút, client cài thêm khi poll |
| WebSocket realtime | **HTTP polling** — agent chủ động hỏi server |

---

## Kiến trúc: Agent core + modules + polling

```
                    ┌─────────────────────────────┐
                    │  Control plane (Django)    │
                    │  command queue + modules   │
                    └───────────┬─────────────────┘
                                │  HTTP polling (outbound)
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
   ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
   │ Worker      │      │ Worker      │      │ Gateway     │
   │ agent core  │      │ agent core  │      │ agent core  │
   │ +docker mod │      │             │      │ +tailscale  │
   └─────────────┘      └─────────────┘      │ +nmap mod   │
         │                                    └─────────────┘
         └── tenant stacks                         └── tailnet
```

### Polling loop (worker + gateway)

```
mỗi ~15s:
  POST /agents/{id}/heartbeat     → online, modules[], inventory
  GET  /agents/{id}/poll        → commands[] + install_module[]
  thực thi → POST /commands/{id}/ack
```

### Modules (gateway)

| Module | Cài khi | Cung cấp |
|--------|---------|----------|
| **core** | `curl \| sh` | poll, enrollment, ip-route scan |
| **tailscale** | Nút UI "Cài Tailscale" | tailscaled, `tailscale_up` |
| **nmap** | Nút UI "Cài Nmap" | `nmap -sn` trên scan_network |

Lệnh `tailscale_up` **chặn** nếu module tailscale chưa cài. `scan_network` dùng core luôn; nmap bổ sung live host count nếu module có.

---

## 7 Phase

### Phase 1–5

Không đổi ý chính — xem bản trước. Bổ sung Phase 1: stub host `gateway-agent.sh` (PLAT-06).

### Phase 6 — Gateway Agent Platform (mới, mở rộng)

**Deliverable:** Gateway cài và điều khiển từ server.

#### One-liner install

```bash
curl -LsSf https://get.my-server.com/gateway-agent.sh | sh
# hoặc với token:
curl -LsSf "https://get.my-server.com/gateway-agent.sh?token=ENROLL_XXX" | sh
```

Script sẽ (core only):
1. Cài gateway agent (systemd)
2. Đăng ký control plane qua enrollment token
3. Bắt đầu **polling loop**
4. Tailscale/nmap — operator cài sau qua nút trên UI server

#### Custom tags (server → gateway)

| Loại | Ví dụ | Ai gán |
|------|-------|--------|
| Bắt buộc | `tag:gateway` | Preauth key bootstrap |
| Tùy chỉnh | `tag:site-hanoi`, `tag:prod` | Operator trên UI/API |

Tags custom phải có trong ACL `tagOwners` của tenant.

#### Lệnh từ server → gateway agent

| Lệnh | Mô tả | Công cụ |
|------|-------|---------|
| **scan_network** | Phát hiện subnet có thể advertise | `ip -4 route` + `ip -4 addr` (chính); `nmap -sn` (tùy chọn nếu có) |
| **tailscale_up** | Kết nối lại Headscale | Xem bảng params bên dưới |
| **tailscale_status** | Báo trạng thái | `tailscale status --json` |

**scan_network:** Ưu tiên parse route/interface (không cần root, không phụ thuộc nmap). Nmap dùng bổ sung để đếm host sống trên subnet — giúp operator chọn CIDR có thiết bị.

**tailscale_up params (server gửi, agent thực thi):**

| Param | Flag | Mặc định gateway |
|-------|------|------------------|
| `login_server` | `--login-server=` | URL Headscale tenant |
| `auth_key` | `--authkey=` | Ref tạm (không log) |
| `advertise_routes` | `--advertise-routes=` | CIDR đã chọn sau scan |
| `force_reauth` | `--force-reauth` | true |
| `accept_dns` | `--accept-dns` | true |
| `accept_routes` | `--accept-routes` | **false** (tránh conflict LAN) |
| `reset` | `--reset` | true khi enroll lại |

#### Plans Phase 6

- 06-01: Agent core + **polling API** (shared worker/gateway) + `gateway-agent.sh`
- 06-02: Module framework + `install_module` command + manifests (tailscale, nmap)
- 06-03: `scan_network` (core ip-route + nmap module) + module gating
- 06-04: Tailscale module: `tailscale_up`, `tailscale_status`, custom tags

**Requirements:** GWA-01..09

---

### Phase 7 — Gateway Operations UI

**Deliverable:** Operator thao tác gateway từ dashboard.

| Tính năng UI | Flow |
|--------------|------|
| Danh sách gateway | Per tenant: hostname, tags, online, modules installed |
| **Cài module** | Nút "Cài Tailscale" / "Cài Nmap" → `install_module` qua poll |
| Copy curl install | Enrollment URL (core only) |
| Scan subnets | Nút Scan → CIDR table (nmap enriches nếu module có) |
| Reconnect | `tailscale_up` — enabled khi tailscale module installed |
| Routes sync | Headscale API: approved/enabled status |

**Requirements:** GW-01..08

---

## Requirements tổng hợp (v1)

**44 requirements** — nhóm mới **GWA** (Gateway Agent):

- GWA-01..09: curl install, enrollment, daemon, tags, scan, tailscale_up
- GW-01..08: UI + Headscale sync (đổi tên/ mở rộng từ GW cũ)
- AGT-01..05: polling protocol, module registry, install_module
- WRK-07: shared agent core
- GWA-01..11: gateway modules + commands

Chi tiết: `.planning/REQUIREMENTS.md`

---

## v2 (sau MVP)

- Route approve/deny từ UI
- CIDR allowlist per tenant
- Scheduled scan + alert subnet mới
- Audit log đầy đủ worker + gateway commands

---

## Tham chiếu kỹ thuật

- Skill: `.cursor/skills/gateway-management/` + `gateway-agent.md`
- Legacy gateway.sh: `headscale-multi-tenants/template/client-setup/gateway.sh`
- Shared agent protocol: Phase 3 `WRK-07`

---

## Bước tiếp theo

```
gsd-discuss-phase 1
gsd-plan-phase 1
gsd-execute-phase 1
```
