---
name: manage-opencode
description: Use when modifying OpenCode configuration, adding MCP servers, changing permissions, restarting the OpenCode service, or troubleshooting OpenCode startup failures
---

# Managing OpenCode

OpenCode runs as a systemd service (`opencode.service`) serving the web UI on port 3456.

## Key Paths

| Path | Purpose |
|------|---------|
| `~/.config/opencode/` | Symlink to `/docker/appdata/opencode/` |
| `/docker/appdata/opencode/` | Canonical config directory (git-tracked in docker repo) |
| `/docker/appdata/opencode/opencode.json` | Main config file |
| `/docker/appdata/opencode/skills/homelab/` | Homelab-specific skills |
| `/docker/appdata/opencode/skills/superpowers` | Symlink to superpowers submodule skills |
| `/docker/appdata/opencode/plugins/` | Plugin entry points |
| `/docker/appdata/opencode/superpowers/` | Git submodule (github.com/obra/superpowers) |
| `/docker/systemd/opencode.service` | Systemd unit file |

## Config Validation

**ALWAYS validate config before restarting the service:**

```bash
opencode debug config
```

- If valid: prints resolved config JSON
- If invalid: prints error with specific field/key that failed

Other useful debug commands:

```bash
opencode debug skill          # List discovered skills
opencode debug paths          # Show config/data/cache directories
opencode debug agent <name>   # Show agent configuration
```

## Config Schema

Config is JSON at `~/.config/opencode/opencode.json`. Key sections:

### Permission

Either a string or per-tool map:

```json
"permission": "allow"
```

```json
"permission": {
  "bash": "ask",
  "edit": "allow"
}
```

Valid values: `"ask"`, `"allow"`, `"deny"`.

**NOT** the Claude Code format (`{ "allow": { "*": true } }`) — that will fail validation.

### MCP Servers

```json
"mcp": {
  "server-name": {
    "type": "local",
    "command": ["bunx", "@some/mcp-server@latest"],
    "enabled": true
  }
}
```

- `bunx` is available system-wide via `/usr/local/bin/bunx` (symlinked from `~/.bun/bin/`)
- `npx` is also available at `/usr/bin/npx`
- Commands must be resolvable from systemd's PATH (no shell profile)

### Full schema reference

```bash
curl -s https://opencode.ai/config.json | jq .
```

## Restart Procedure

```bash
# 1. Validate FIRST
opencode debug config

# 2. Only if validation passes
sudo systemctl restart opencode

# 3. Verify it started
sudo systemctl status opencode
sudo journalctl -u opencode -n 20 --no-pager
```

**NEVER restart without validating.** A bad config will crash-loop the service.

## Systemd Service

```bash
sudo systemctl status opencode      # Check status
sudo systemctl restart opencode     # Restart
sudo journalctl -u opencode -f      # Follow logs
sudo journalctl -u opencode -n 50   # Recent logs
```

The service runs as user `will` with `WorkingDirectory=/home/will`. It does NOT source shell profiles, so tools must be on the system PATH.

## PATH Considerations

Systemd services don't source shell profiles. Tools installed via asdf or bun are NOT on the system PATH unless symlinked:

| Tool | System path | Source |
|------|-------------|--------|
| `bun` / `bunx` | `/usr/local/bin/` | Symlinked from `~/.bun/bin/` |
| `node` | `/usr/local/bin/` | Symlinked from `~/.asdf/installs/nodejs/*/bin/` |
| `npx` | `/usr/bin/npx` | System package (uses system npm — may conflict with modern node) |

**Note:** The system `npx` at `/usr/bin/npx` is tied to Ubuntu's npm package. If `/usr/local/bin/node` points to a modern version (22+), system npx will break with `Cannot find module '@npmcli/config'`. Use `bunx` instead, or install npm via asdf.

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Unrecognized keys" on startup | Wrong config key names | Check schema — OpenCode uses `permission` not `permissions`, `mcp` not `mcpServers` |
| "Invalid input permission" | Wrong permission format | Use `"allow"` string or `{ "tool": "action" }` map |
| MCP server "Connection closed" | MCP process crashes on start | Run the command manually to see error: `timeout 5 bunx @some/mcp@latest 2>&1` |
| `Cannot find module 'node:events'` | System node too old for MCP package | Symlink modern node to `/usr/local/bin/node` |
| `Cannot find module '@npmcli/config'` | System npx incompatible with modern node | Use `bunx` instead of `npx` |
| MCP server not in PATH | Command not resolvable from systemd | Symlink binary to `/usr/local/bin/` |
| Config not found | Wrong file location | Must be at `~/.config/opencode/opencode.json` (not in a subdirectory) |
| Skills not discovered | Wrong directory | Must be under `~/.config/opencode/skills/{group}/{name}/SKILL.md` |

## Adding an MCP Server

1. Edit `/docker/appdata/opencode/opencode.json`
2. Add entry under `"mcp"` key
3. **Test the command manually first:** `timeout 5 bunx @the/mcp-server 2>&1`
4. Validate config: `opencode debug config`
5. Restart: `sudo systemctl restart opencode`
6. Verify: `opencode mcp list` or check service logs
