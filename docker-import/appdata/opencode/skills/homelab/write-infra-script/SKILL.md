---
name: write-infra-script
description: Use when writing utility scripts, creating automation tools, or adding new scripts to the homelab bin directory
---

# Writing Infrastructure Scripts

Location: `/docker/bin/`

## Checklist

- [ ] Write script following conventions below
- [ ] `chmod +x /docker/bin/{script}`
- [ ] Test with `--help` or dry-run if applicable
- [ ] Update `/docker/bin/AGENTS.md` inventory table

## Script Template

```bash
#!/bin/bash
set -euo pipefail

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
print_status()  { echo -e "${GREEN}[OK]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

# --- Config ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Usage ---
usage() {
    echo "Usage: $(basename "$0") <required_arg> [optional_arg]"
    echo ""
    echo "Description of what this script does."
    echo ""
    echo "Arguments:"
    echo "  required_arg    What it is"
    echo "  optional_arg    What it is (default: something)"
    exit 1
}

# --- Argument validation ---
if [ $# -lt 1 ]; then
    print_error "Missing required argument"
    usage
fi

# --- Main ---
# ...
```

## Conventions

### 1. Header and Safety

| Script type | Header |
|-------------|--------|
| Standard utility | `set -e` |
| Critical / data-modifying | `set -euo pipefail` |
| Simple wrapper | No set flags needed |

### 2. Simple Wrappers

For thin wrappers, a single `exec` line is fine (see `drestic` as example):

```bash
#!/bin/bash
exec docker exec restic-backup restic -r /Volumes/Bonus1/lafayette "$@"
```

### 3. Secrets Access

```bash
# From the host
source /docker/config/secrets/{service}_env

# Inside a container (check both paths)
if [ -f /app/secrets/{service}_env ]; then
    source /app/secrets/{service}_env
else
    source /docker/config/secrets/{service}_env
fi
```

### 4. Docker Interaction

```bash
# Run command in a container
docker exec -it {container} {command}

# Get container name from service name
docker-name {service}

# Compose operations (always specify service)
cd /docker/config && docker compose up -d {service}
cd /docker/config && docker compose logs -f {service}
```

### 5. Authentik API

Pattern from existing scripts:

```bash
source /docker/config/secrets/authentik_api_env

# GET request
curl -s -H "Authorization: Bearer $AUTHENTIK_API_TOKEN" \
    "http://localhost:9000/api/v3/{endpoint}/"

# POST request
curl -s -X POST \
    -H "Authorization: Bearer $AUTHENTIK_API_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"key": "value"}' \
    "http://localhost:9000/api/v3/{endpoint}/"
```

### 6. Calling Sibling Scripts

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/other-script" arg1 arg2
```

### 7. Output Style

- Use `print_status` / `print_warning` / `print_error` for user-facing output
- Use plain `echo` for data output that might be piped
- Write errors to stderr: `print_error "msg" >&2`

## Existing Scripts Reference

Check `/docker/bin/` for examples. Key scripts:

| Script | Purpose |
|--------|---------|
| `add-user` | Multi-service user provisioning |
| `list-users` | Authentik API query example |
| `sync-users` | Cross-service sync pattern |
| `drestic` | Simple exec wrapper example |

Read one or two of these before writing a new script to match the local style.
