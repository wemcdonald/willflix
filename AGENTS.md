# Infrastructure Overview

Docker-based homelab on `willflix.org`. All services at `{name}.willflix.org`.

## Directory Structure

```
/docker/
├── appdata/     # Persistent service data       → see appdata/AGENTS.md
├── bin/         # Utility scripts               → see bin/AGENTS.md
├── config/      # Compose, Traefik, secrets     → see config/AGENTS.md
├── logs/        # Service log output
├── setup/       # Installation scripts and docs → see setup/AGENTS.md
└── systemd/     # Systemd unit files            → see systemd/AGENTS.md
```

## Networks

| Network | Purpose |
|---------|---------|
| `traefik_public` | External-facing services behind Traefik reverse proxy |
| `default` | Internal communication (PostgreSQL, Redis, service-to-service) |
| `homebot_network` | Isolated Telegram bot services |

Services typically join `traefik_public` for web access and `default` for database access.

## Remote Access

- **Public:** `{name}.willflix.org` via Traefik (HTTPS, most services behind Authentik)
- **Tailscale:** Host is `willflix` (`100.87.47.17`) on the tailnet, MagicDNS domain `tail88dba.ts.net`. Services binding `0.0.0.0` are reachable directly by port (e.g., `willflix.tail88dba.ts.net:3456` for OpenCode). No auth layer on Tailscale — access is network-gated.

## Safety Rules

**NEVER run bare `docker compose up -d` or `docker compose down` without specifying service names.** This will restart or destroy ALL services on the host.

**Secrets in `/docker/config/secrets/` are encrypted with git-crypt.** Never commit plaintext secrets. If git-crypt is not unlocked, secret files will appear as binary — do not overwrite them.

## Subdirectory Guides

| File | Covers |
|------|--------|
| `config/AGENTS.md` | Compose patterns, Traefik labels, authentication, VPN routing, secrets |
| `bin/AGENTS.md` | Script inventory, conventions for writing new scripts |
| `systemd/AGENTS.md` | Unit file templates, enable/disable procedure, management commands |
| `appdata/AGENTS.md` | Git tracking strategy, .gitignore layering, adding new services |
| `setup/AGENTS.md` | Host packages, installation scripts, setup documentation |
