# Repo Consolidation — Design

**Date**: 2026-03-04
**Status**: Complete

---

## Goals

Consolidate ~/willflix and /docker into a single repo at `/willflix`. One repo for all system configuration — Docker services, cron scripts, system configs, secrets, and documentation. Function-based layout, not tool-based.

---

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Repo location | `/willflix` | Top-level, matches `/docker` convention. Not buried under home. |
| Merge strategy | git subtree | Preserves /docker's commit history in the merged repo. |
| Layout | By function (bin/, etc/, docker/, secrets/) | Operator thinks "configure the server", not "is this a Docker thing or a cron thing". |
| Secrets | Fresh git-crypt init | Cleaner than migrating git-crypt state across subtree merge. |
| Path transition | Symlinks | `/docker` → `/willflix/docker`. Nothing breaks day one. |
| server-config | Deprecate | Stale since July 2025, overlaps both repos, not version-controlled. |

---

## Target Layout

```
/willflix/
├── bin/
│   ├── cron/                  # All cron scripts
│   ├── willflix-notify         # Notification tools
│   ├── willflix-notify-send
│   ├── sendmail-system         # From /docker/bin/
│   ├── add-user                # From /docker/bin/
│   └── ...                     # Other admin scripts from /docker/bin/
├── docker/
│   ├── compose.yml             # From /docker/config/docker-compose.yml
│   ├── traefik-middlewares.yml # From /docker/config/
│   ├── nginx-public.conf       # From /docker/config/
│   ├── nginx-webhook.conf      # From /docker/config/
│   └── appdata/                # From /docker/appdata/ (gitignored)
├── etc/
│   ├── smartd.conf             # SMART monitoring config
│   ├── root-crontab            # Root crontab backup
│   ├── fstab                   # Tracked copy from /etc/
│   ├── snapraid.conf           # Tracked copy from /etc/
│   ├── systemd/                # From /docker/systemd/
│   └── willflix-*.conf/ignore  # Monitoring configs
├── secrets/                    # git-crypt encrypted
│   └── (all secrets from /docker/config/secrets/)
├── docs/                       # PRDs, postmortems, runbooks, plans
├── .gitattributes              # git-crypt filter rules
└── .gitignore                  # appdata, logs, etc.
```

---

## Migration Strategy

### Pre-requisite: Move ~/willflix to /willflix

```bash
sudo mv ~/willflix /willflix
sudo chown -R will:will /willflix
ln -s /willflix ~/willflix   # optional convenience symlink
```

Update any references (crontab paths, symlinks, CLAUDE.md).

### Phase 1: Subtree merge

Bring /docker's full git history into /willflix under a temporary prefix:

```bash
cd /willflix
git subtree add --prefix=docker-import /docker master
```

Rearrange files from `docker-import/` into the target layout:
- `docker-import/config/docker-compose.yml` → `docker/compose.yml`
- `docker-import/config/secrets/` → `secrets/`
- `docker-import/config/*.yml, *.conf` → `docker/`
- `docker-import/bin/` → `bin/`
- `docker-import/systemd/` → `etc/systemd/`
- `docker-import/appdata/` → `docker/appdata/`
- `docker-import/logs/` → `docker/logs/` (gitignored)

Remove `docker-import/` after rearranging. Commit.

### Phase 2: git-crypt setup

1. `git-crypt init`
2. Add GPG key: `git-crypt add-gpg-user <KEY_ID>`
3. Configure `.gitattributes`: `secrets/** filter=git-crypt diff=git-crypt`
4. Secrets are now in `secrets/` and will be encrypted on push
5. Commit

### Phase 3: Symlinks for compatibility

```bash
# Primary symlink — makes all /docker paths work
sudo ln -sfn /willflix/docker /docker

# Compose needs to find secrets at config/secrets/
ln -s /willflix/secrets /willflix/docker/config/secrets

# Cron scripts (may already exist)
ln -sfn /willflix/bin/cron ~/bin/cron
```

All existing references to `/docker/config/docker-compose.yml`, `/docker/appdata/`, `/docker/bin/` continue to work through the symlink.

### Phase 4: Add untracked system configs

```bash
cp /etc/fstab /willflix/etc/fstab
cp /etc/snapraid.conf /willflix/etc/snapraid.conf
```

Commit.

### Phase 5: Cleanup (gradual, not blocking)

- Update hardcoded `/docker/config/` paths in scripts to use new locations
- Update CLAUDE.md and AGENTS.md to reflect new layout
- Update crontab paths from `/home/will/bin/cron/` to `/willflix/bin/cron/`
- Archive the /docker GitHub repo on GitHub
- Deprecate ~/server-config/ (move any unique content first, then remove)
- Push /willflix to GitHub (new remote, or rename existing willflix remote)

---

## Symlink Map

| Symlink | Target | Purpose |
|---------|--------|---------|
| `/docker` | `/willflix/docker` | All /docker paths work unchanged |
| `/willflix/docker/config/secrets` | `/willflix/secrets` | Compose finds secrets at expected path |
| `~/bin/cron` | `/willflix/bin/cron` | Cron scripts accessible from home |
| `~/willflix` | `/willflix` | Optional convenience |

---

## What Gets Gitignored

```gitignore
docker/appdata/
docker/logs/
*.pyc
__pycache__/
```

`appdata/` is container data (databases, config files, media indexes). Huge, constantly changing, not suitable for git. Backed up separately (pg_dump for databases, restic for configs).

---

## Risk Mitigation

- **Symlinks mean nothing breaks on day one.** Every existing path resolves correctly.
- **Compose commands work unchanged:** `cd /docker && docker compose up -d` still works because `/docker` → `/willflix/docker`.
- **Secrets stay encrypted:** Fresh git-crypt with your GPG key. Secrets never appear in plaintext in git history.
- **Rollback:** If anything goes wrong, remove symlinks and move /docker back. The original /docker repo is untouched until we archive it.
- **Gradual cleanup:** Path updates happen over time, not all at once.
