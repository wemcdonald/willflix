# Utility Scripts

## Script Inventory

| Script | Purpose | Usage |
|--------|---------|-------|
| `add-user` | Create user across Authentik + Calibre-Web + Nextcloud + Plex | `add-user username email [admin\|user]` |
| `add-calibre-user` | Add user to Calibre-Web only | `add-calibre-user username email [role]` |
| `sync-users` | Sync Authentik group members to Calibre-Web | `sync-users [username]` |
| `invite-to-plex` | Send Plex server sharing invite | `invite-to-plex email` |
| `list-users` | List all Authentik users | `list-users` |
| `email-users` | Send templated email to users | `email-users template email... \| --all` |
| `sendmail-system` | System sendmail replacement routing through Docker smtp-relay | Called by system mail tools |
| `test-mail` | Test the Docker mail pipeline | `test-mail` |
| `drestic` | One-liner wrapper for restic inside Docker | `drestic snapshots`, `drestic stats`, etc. |
| `webhook-server.py` | HTTP server for Authentik `user.created` webhooks | Runs as daemon; triggers `sync-users` |

## Conventions for New Scripts

### Shebang and error handling

```bash
#!/bin/bash
set -e                    # Simple scripts
set -euo pipefail         # Critical scripts (mail, user provisioning)
```

### Secrets

```bash
source /docker/config/secrets/authentik_api_env
```

For scripts that also run inside containers (like webhook-handler), check both paths:
```bash
if [ -f /app/secrets/authentik_api_env ]; then
    source /app/secrets/authentik_api_env
else
    source /docker/config/secrets/authentik_api_env
fi
```

### Color output

```bash
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_status()  { echo -e "${GREEN}[OK]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
```

### Argument validation

```bash
if [ $# -lt 2 ]; then
    echo "Usage: $(basename "$0") username email [admin|user]"
    exit 1
fi
```

### Resolving sibling scripts

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/sync-users"
```

### Simple wrappers

Single `exec` line forwarding all arguments (e.g., `drestic`):

```bash
exec docker exec restic-backup restic "$@"
```

### Permissions

```bash
chmod +x /docker/bin/my-new-script
```
