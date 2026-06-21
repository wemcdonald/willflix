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

## 3. Migrate Plex data to NVMe (deferred — needs the SATA SSD connected)

Cannot run yet: the Crucial BX500 Plex SSD isn't connected. When it is:

```bash
# stop Plex, create the dataset at the SAME mountpoint so compose paths don't change
sudo docker compose -p config stop plex
sudo zfs create -o compression=zstd -o atime=off -o mountpoint=/Volumes/Plex.new rpool/plex
sudo rsync -aHAX --numeric-ids --info=progress2 /Volumes/Plex/ /Volumes/Plex.new/
sudo umount /Volumes/Plex 2>/dev/null || true        # unmount the SATA drive
sudo zfs set mountpoint=/Volumes/Plex rpool/plex
sudo docker compose -p config up -d plex
```
Keep `/Volumes/PlexTranscode` on tmpfs (fstab) — never on the snapshotted dataset.
Consider a child `rpool/plex/cache` with `com.sun:auto-snapshot=false` if thumbnail
churn bloats snapshots. Then uncomment `rpool/plex` in `etc/zfs-snapshot.conf` and
remove the old SATA Plex entry from `etc/smartd.conf`.

Plex data is already backed up separately (restic `plex` tag + Plex DB backup), so
the dataset snapshots are an additional fast-restore layer, not the only copy.
