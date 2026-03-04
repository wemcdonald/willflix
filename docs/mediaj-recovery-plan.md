# MediaJ Recovery Plan

**Created**: 2026-03-03

## Phase 1: Stop the Bleeding

- [x] 1.1 Kill stuck snapraid processes (hung since Dec 19, 2025)
- [x] 1.2 Remove stale lock file
- [x] 1.3 Unmount dead MediaJ (lazy unmount of zombie sdh1 mount)

## Phase 2: Assess the Damage

- [~] 2.1 Run read-only fsck on /dev/sdu1 — SKIPPED: superblock says "clean", bad sectors are media-level not FS-level. debugfs too slow on 11TB drive.
- [x] 2.2 Attempt read-only mount to temporary location — SUCCESS: mounted at /tmp/mediaj-recovery
- [x] 2.3 Inventory what files exist on MediaJ — All top-level dirs readable (Movies: 292, TV: 246, Movies4K: 3, TV4K: 3, KidsTV: 14, Stand-Up: 11, YouTube: 4, plus Calibre, Downloads, Backup, etc.)
- [x] 2.4 Categorized files by parity protection — 20 movies, ~1146 TV eps, 205 KidsTV, 488 audiobooks, 3174 Calibre files have NO parity. Quick read tests show unprotected files are readable.

## Phase 3: Recover Data (LONG-RUNNING — USER RUNNING MANUALLY)

- [ ] 3.1 Rsync all data from dying drive to MediaSpare (salvage unprotected files first)
      ```
      sudo rsync -a --progress --info=progress2 --no-inc-recursive --ignore-errors \
        /tmp/mediaj-recovery/ /Volumes/MediaSpare/
      ```
- [ ] 3.2 Run `snapraid fix -d d10` to overwrite with parity-protected data where available
      ```
      sudo snapraid fix -d d10 -l /tmp/snapraid-fix.log
      ```
- [ ] 3.3 Verify results — check rsync/snapraid logs for errors
      ```
      grep -i "error\|unrecoverable" /tmp/snapraid-fix.log
      ```
- [ ] 3.4 Identify permanently lost files (post-May-2025, on bad sectors)

## Phase 4: Retire Old Drive & Rebuild Array

- [ ] 4.1 Unmount dying MediaJ: `sudo umount /tmp/mediaj-recovery`
- [ ] 4.2 Physically remove or disconnect old drive (WDC WD120EMAZ, serial 8CGR2NSE, /dev/sdu)
- [ ] 4.3 Relabel MediaSpare → MediaJ: `sudo e2label /dev/sdm1 MediaJ`
- [ ] 4.4 Update fstab: remove or comment out the `LABEL=MediaSpare` line (existing `LABEL=MediaJ` line handles the mount)
- [ ] 4.5 Mount new MediaJ: `sudo mount /Volumes/MediaJ`
- [ ] 4.6 Remount mergerfs so it picks up the new drive (or reboot)
- [ ] 4.7 Update snapraid.conf: d10 path stays `/Volumes/MediaJ/` (no change needed)
- [ ] 4.8 Run full snapraid sync — **LONG-RUNNING**
      ```
      sudo snapraid sync
      ```
- [ ] 4.9 Run snapraid scrub to validate parity — **LONG-RUNNING**
      ```
      sudo snapraid scrub
      ```

## Phase 5: Rebuild App State

- [ ] 5.1 Unpause radarr and sonarr
- [ ] 5.2 Plex: scan library to detect recovered/missing media
- [ ] 5.3 Radarr: check for missing movies, re-download if needed
- [ ] 5.4 Sonarr: check for missing episodes, re-download if needed

## Phase 6: Prevent Recurrence (from post-mortem)

- [ ] 6.1 Set up SMART monitoring with alerting (smartd or similar)
- [ ] 6.2 Add timeout to snapraid cron scripts
- [ ] 6.3 Add staleness alerting (warn if no sync in N days)
- [ ] 6.4 Add mergerfs health check (verify all member drives readable)
- [ ] 6.5 Add filesystem remount-ro alerting
- [ ] 6.6 Consider snapraid-runner or similar wrapper with built-in safeguards
- [ ] 6.7 Acquire a new spare drive to replace MediaSpare's role

## Current State (updated 2026-03-04)

**Recovery in progress:**
- rsync from `/tmp/mediaj-recovery/` → `/Volumes/MediaSpare/` running in user's tmux (~38hrs at 70MB/s)
- After rsync: run `sudo snapraid fix -d d10 -l /tmp/snapraid-fix.log`
- After fix: Phase 4 (relabel MediaSpare → MediaJ, rebuild array)

**Drives:**
- **Old MediaJ** (dying): Read-only mounted at `/tmp/mediaj-recovery` (`/dev/sdu1`, WDC WD120EMAZ, serial 8CGR2NSE). To be retired and physically removed.
- **MediaSpare** (recovery target): 13TB at `/Volumes/MediaSpare` (`/dev/sdm1`). Will be relabeled to MediaJ after recovery.
- **MediaC** (sdb): 6 pending sectors, SMART long test started 2026-03-04 ~13:30, est. 7.5hrs.

**Infrastructure fixes applied 2026-03-04 (P0):**
- Killed stuck snapraid processes, removed stale lock, fixed stale content file
- Rewrote snapraid_daily/weekly/check_for_deletes with timeouts and alerting
- Added check_snapraid_freshness (daily 8:30am) and check_mergerfs_health (every 15min) to root crontab
- Fixed `MAILTO=""` suppression in root crontab, removed cronic wrapper from snapraid jobs
- Fixed sendmail-system (netcat→curl) — ALL prior email alerts were silently dropped
- Rewrote /etc/smartd.conf: 18 drives pinned by stable ata-ID paths, monthly self-tests
- Root cause of May–Dec sync gap identified (interrupted sync + MAILTO="" suppression)

**Still pending:**
- MergerFS: MediaJ is not in the pool. Files on MediaJ are not visible through `/Volumes/Media`.
- SnapRAID: Unlocked, not running. Content files synced to May 1, 2025 snapshot. Triple parity intact.
- Radarr/Sonarr: Should be paused during recovery to avoid wasted re-downloads.
