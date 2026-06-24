# ZFS datasets on mulligan (2026-06)

mulligan's root is ZFS (`rpool` + `bpool`) on a WD_BLACK SN7100 2TB NVMe. We split
app data into its own datasets so it can be snapshotted, rolled back, tuned, and
quota'd independently of the OS root.

Layout (target):

| Dataset | Mountpoint | Props | Notes |
|---------|-----------|-------|-------|
| `rpool/willflix` | `/willflix` | `compression=zstd atime=off xattr=sa` | docker appdata + repo |
| `rpool/willflix/postgres` | `/willflix/docker/appdata/postgres` | `recordsize=16K` | DB perf; created at restore time |
| `rpool/USERDATA/home_*` | `/home` | (install default) | already its own dataset |
| `rpool/plex` | `/Volumes/Plex` | `compression=zstd atime=off` | created when Plex moves to NVMe |

Snapshots: `bin/cron/zfs-snapshot` (config `etc/zfs-snapshot.conf`), hourly keep 24 +
daily keep 14, recursive, pruned per label. Missing datasets are skipped.

---

## 1. Migrate /willflix to its own dataset (do now)

`/willflix` currently lives inside the root dataset. Move it:

```bash
sudo /willflix/bin/zfs-migrate-willflix
```
The script: creates `rpool/willflix`, rsyncs `/willflix` into it (live), then stops
Docker, does a delta rsync, swaps the mountpoint, verifies, and restarts the stack.
Old data is kept at `/willflix.old` until you `sudo rm -rf /willflix.old`.

Mount ordering: ZFS auto-mounts at boot before `docker.service`, so containers see a
populated `/willflix`. If you ever see empty appdata after a reboot, check
`systemctl status zfs-mount.service`.

## 2. Postgres child dataset (do at the Phase-B DB restore)

Best done when `appdata/postgres` is empty — i.e. right before restoring the dumps
(rebuild Stage 8). Create the tuned child, then restore into it:

```bash
sudo docker compose -p config stop postgres
sudo rm -rf /willflix/docker/appdata/postgres        # empty/fresh cluster only
sudo zfs create -o recordsize=16K -o mountpoint=/willflix/docker/appdata/postgres rpool/willflix/postgres
sudo chown 999:999 /willflix/docker/appdata/postgres # match the postgres image UID
sudo docker compose -p config up -d postgres
# then restore dumps per docs/disaster-recovery.md (Stage 8)
```

## 3. Migrate Plex data to NVMe

`bin/zfs-migrate-plex` is **fully unattended** — schedule it overnight as root:
```bash
sudo apt install -y at && sudo systemctl enable --now atd   # if `at` isn't present
echo /willflix/bin/zfs-migrate-plex | sudo at 01:00          # runs as root at 1am
sudo atq                                                     # verify it's queued
# morning review:
tail -n 120 /willflix/log/zfs-migrate-plex.log
```
Steps (the rsync of ~880G / ~1.5M files takes 1-3h): create `rpool/plex` (zstd,
atime=off) → **bulk rsync while Plex stays up** (no downtime; excludes regenerable
`Cache/`) → **stop Plex** → **delta rsync** (DB copies clean) → **verify** (df +
`md5sum` of the library DB, source vs copy) → **chown -R 122:129** (Plex's uid/gid)
→ comment the SATA `LABEL=Plex` line in `/etc/fstab` (backup saved) → unmount SATA →
mount the dataset at `/Volumes/Plex` → re-verify DB md5 → restart Plex.
Downtime ≈ the delta pass (minutes). It emits a `willflix-notify` on success/failure.

**Fail-safe:** any error *before* the mountpoint swap restores the original state —
SATA remounted at `/Volumes/Plex`, `/etc/fstab` restored, Plex restarted — so a failed
run never leaves a half-migration. The SATA copy is always left **intact + unmounted**.
Logging is step-level only (rsync per-file chatter goes to `…rsync.log`).

Mountpoint stays `/Volumes/Plex`, so compose (`/Volumes/Plex:/Volumes/Plex` +
`PLEX_MEDIA_SERVER_APPLICATION_SUPPORT_DIR=/Volumes/Plex`) is unchanged.

Post-migration follow-ups (commit together):
- mirror the fstab change into the repo: comment the `LABEL=Plex` line in `etc/fstab`
- uncomment `rpool/plex` in `etc/zfs-snapshot.conf`
- `/Volumes/PlexTranscode` stays tmpfs (fstab) — never on the dataset
- optional: child `rpool/plex/cache` with `com.sun:auto-snapshot=false` if Cache churn bloats snapshots
- keep the SATA `smartd.conf` entry until the drive is physically repurposed

Plex data is already backed up separately (restic `plex` tag + Plex DB backup), so
the dataset snapshots are an additional fast-restore layer, not the only copy.
