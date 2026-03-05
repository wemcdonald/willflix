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

## Phase 3: Recover Data

- [x] 3.1 Rsync all data from dying drive to MediaSpare (salvage unprotected files first)
      ```
      sudo rsync -a --progress --info=progress2 --no-inc-recursive --ignore-errors \
        /tmp/mediaj-recovery/ /Volumes/MediaSpare/
      ```
      **DONE** — ~10.6TB transferred in ~20hrs. 8 files failed (bad sectors):
      - `Downloads/completed_nzb/Movies/Green.Book.2018...mkv`
      - `Downloads/completed_nzb/Series/Formula.1...S08E08...mkv`
      - `Downloads/completed_nzb/Series/Love.Island.S07E04...mkv`
      - `TV/Fallout/Season 02/S02E01 - The Father.mkv`
      - `TV/Formula 1.../Season 08/S08E02 - Strictly Business.mkv`
      - `TV/Love Is Blind/Season 10/S10E09 - I'm Just Being Honest.mkv`
      - `TV/Shrinking/Season 03/S03E02 - Happiness Mission.mkv`
      - `TV/The Pitt/Season 02/S02E07 - 1-00 P.M.mkv`
      rsync correctly discarded all 8 corrupt copies ("failed verification — update discarded").

## Phase 4: Swap Drives & Restore from Parity

**NOTE**: Steps reordered from original plan — the drive must be relabeled and
mounted as MediaJ BEFORE snapraid fix, because snapraid writes to the path
configured for d10 (`/Volumes/MediaJ/`), not to MediaSpare.

- [ ] 4.1 Unmount dying MediaJ: `sudo umount /tmp/mediaj-recovery`
- [ ] 4.2 Disable snapraid cron jobs temporarily (prevent sync during transition)
      ```
      sudo crontab -e
      # Comment out these 3 lines:
      #   0 1 * * 0 /home/will/bin/cron/snapraid_weekly
      #   0 1 * * 1-6 /home/will/bin/cron/snapraid_daily
      #   30 8 * * * /home/will/bin/cron/check_snapraid_freshness
      ```
      **WHY**: snapraid_daily uses `--force-zero` and runs at 1am. If it runs
      mid-transition it could corrupt parity. check_for_deletes would likely
      block it, but disabling is safer.
- [ ] 4.3 Unmount MediaSpare: `sudo umount /Volumes/MediaSpare`
- [ ] 4.4 Relabel MediaSpare → MediaJ: `sudo e2label /dev/sdm1 MediaJ`
- [ ] 4.5 Mount new MediaJ: `sudo mount /Volumes/MediaJ`
- [ ] 4.6 Run `snapraid fix -d d10` to overwrite with parity-protected data — **LONG-RUNNING**
      ```
      sudo snapraid fix -d d10 -l /tmp/snapraid-fix.log
      ```
      This reconstructs ~1M files from May 2025 parity onto the new drive,
      overwriting rsync'd copies with known-good parity-verified versions.
      Post-May-2025 files (from rsync) are left untouched.
- [ ] 4.7 Verify fix results
      ```
      grep -i "error\|unrecoverable" /tmp/snapraid-fix.log
      ```
- [ ] 4.8 Identify permanently lost files — the 8 rsync failures that are also
      post-May-2025 (no parity). The 3 Downloads files definitely have no parity.
      The 5 TV files (Fallout S02, F1 S08, Love Is Blind S10, Shrinking S03,
      The Pitt S02) are likely post-May-2025 but worth checking the fix log.
- [ ] 4.9 Run full snapraid sync — **LONG-RUNNING**
      ```
      sudo snapraid sync
      ```
- [ ] 4.10 Run snapraid scrub to validate parity — **LONG-RUNNING**
      ```
      sudo snapraid scrub
      ```
- [ ] 4.11 Comment out MediaSpare line in fstab (label no longer exists)
      ```
      sudo sed -i 's/^LABEL=MediaSpare/#LABEL=MediaSpare/' /etc/fstab
      ```
- [ ] 4.12 Remount mergerfs so pool picks up new MediaJ content (or reboot)
      ```
      # This briefly interrupts Plex/etc reading from /Volumes/Media
      sudo umount /Volumes/Media && sudo mount /Volumes/Media
      ```
      Note: mergerfs already has /Volumes/MediaJ as a branch (glob matched at
      boot), but remounting ensures a clean state with the real drive.
- [ ] 4.13 Re-enable snapraid cron jobs (uncomment the 3 lines from step 4.2)
- [ ] 4.14 Physically remove or disconnect old drive (WDC WD120EMAZ, serial 8CGR2NSE, /dev/sdu) — can wait until next maintenance window

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

## Current State (updated 2026-03-04, evening)

**Rsync complete. Ready for Phase 4 (drive swap + parity restore).**

**Next step**: 4.1 — unmount dying drive.

**Drives:**
- **Old MediaJ** (dying): Read-only mounted at `/tmp/mediaj-recovery` (`/dev/sdu1`, WDC WD120EMAZ, serial 8CGR2NSE). To be unmounted and retired.
- **MediaSpare** (has rsync'd data): 9.6TB used, at `/Volumes/MediaSpare` (`/dev/sdm1`). Will be relabeled to MediaJ.
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
- SnapRAID: Unlocked, not running. Content files synced to May 1, 2025 snapshot. Triple parity intact (~1M files on d10).
- Radarr/Sonarr: Running but should be paused during recovery to avoid wasted re-downloads.
