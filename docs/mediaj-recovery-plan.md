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

- [x] 4.1 Unmount dying MediaJ: `sudo umount /tmp/mediaj-recovery`
- [x] 4.2 Disable snapraid cron jobs temporarily (prevent sync during transition)
- [x] 4.3 Unmount MediaSpare: `sudo umount /Volumes/MediaSpare`
- [x] 4.4 Relabel MediaSpare → MediaJ: `sudo e2label /dev/sdm1 MediaJ`
- [x] 4.5 Mount new MediaJ: `sudo mount /Volumes/MediaJ`
- [~] 4.6 snapraid fix -d d10 — SKIPPED: aborted by MediaC read errors (missing
      Plex cache files on bad sectors). Ran audit check instead — also too slow.
      Decision: skip parity restore, re-download the 8 missing files instead.
      Risk of silent corruption on rsync'd files is low for media library.
- [x] 4.7 Old dying drive physically removed (`/dev/sdu`, WDC WD120EMAZ, serial 8CGR2NSE)
- [x] 4.8 New 16.4TB drive installed, formatted, mounted at `/Volumes/MediaParity3.New` (`/dev/sdh1`)

### Phase 4b: Replace MediaParity3 & MediaC (pre-sync)

Replacing two drives before running sync so it all gets done in one pass.

- **Old MediaParity3**: `/dev/sdc1`, WDC WD140EDGZ-11B1PA0, serial XHG930GH, 12.7TB
- **New parity drive**: `/dev/sdh1`, 16.4TB, currently `LABEL=MediaParity3.New` at `/Volumes/MediaParity3.New`
- **MediaC** (sdb): Seagate ST33000651AS, serial 9XK071TZ, 2.7TB, 67K hours, 6 pending sectors — highest failure risk

**Plan**: Copy parity3 → new drive, then reformat old parity3 (12.7TB) as new MediaC,
copy MediaC data → new MediaC, retire old MediaC.

- [ ] 4b.1 Copy parity data to new drive — **LONG-RUNNING**
      ```
      sudo rsync -a --progress /Volumes/MediaParity3/snapraid.parity /Volumes/MediaParity3.New/
      ```
- [ ] 4b.2 Unmount old MediaParity3: `sudo umount /Volumes/MediaParity3`
- [ ] 4b.3 Relabel new drive: `sudo e2label /dev/sdh1 MediaParity3`
- [ ] 4b.4 Mount new MediaParity3: `sudo umount /Volumes/MediaParity3.New && sudo mount /Volumes/MediaParity3`
- [ ] 4b.5 Reformat old parity drive as MediaC replacement:
      ```
      sudo mkfs.ext4 -L MediaC.New /dev/sdc1
      sudo mkdir -p /Volumes/MediaC.New && sudo mount /dev/sdc1 /Volumes/MediaC.New
      ```
- [ ] 4b.6 Copy MediaC data to new drive — **LONG-RUNNING**
      ```
      sudo rsync -a --progress /Volumes/MediaC/ /Volumes/MediaC.New/
      ```
- [ ] 4b.7 Unmount old MediaC: `sudo umount /Volumes/MediaC`
- [ ] 4b.8 Relabel new MediaC: `sudo e2label /dev/sdc1 MediaC`
- [ ] 4b.9 Mount new MediaC: `sudo umount /Volumes/MediaC.New && sudo mount /Volumes/MediaC`
- [ ] 4b.10 Update snapraid.conf if parity path changed (check — should be same path)
- [ ] 4b.11 Physically remove old MediaC (Seagate ST33000651AS, serial 9XK071TZ)

### Phase 4c: Sync & Finalize

- [ ] 4c.1 Run full snapraid sync — **LONG-RUNNING**
      ```
      sudo snapraid sync
      ```
      This covers: new MediaJ (d10), new MediaC (d3), and new MediaParity3 in one pass.
- [ ] 4c.2 Run snapraid scrub to validate parity — **LONG-RUNNING**
      ```
      sudo snapraid scrub
      ```
- [ ] 4c.3 Comment out MediaSpare line in fstab (label no longer exists)
      ```
      sudo sed -i 's/^LABEL=MediaSpare/#LABEL=MediaSpare/' /etc/fstab
      ```
- [ ] 4c.4 Remount mergerfs so pool picks up new drive content (or reboot)
      ```
      sudo umount /Volumes/Media && sudo mount /Volumes/Media
      ```
- [ ] 4c.5 Re-enable snapraid cron jobs
- [ ] 4c.6 Update smartd.conf with new drive serial numbers

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

## Current State (updated 2026-03-05)

**MediaJ swapped. Now replacing MediaParity3 and MediaC before running sync.**

**Next step**: 4b.1 — copy parity3 to new drive.

**Drives:**
- **MediaJ** (`/dev/sdm1`, 12.7TB): Restored from rsync. Mounted, in mergerfs. 8 files missing (to re-download).
- **Old MediaJ**: Physically removed and retired.
- **MediaParity3** (`/dev/sdc1`, 12.7TB): Current parity drive, to be reformatted as MediaC replacement.
- **MediaParity3.New** (`/dev/sdh1`, 16.4TB): New drive, empty, mounted at `/Volumes/MediaParity3.New`. Will become MediaParity3.
- **MediaC** (`/dev/sdb`, 2.7TB): Seagate ST33000651AS, 67K hours, 6 pending sectors. To be retired.

**Snapraid cron**: Disabled (step 4.2). Must re-enable after sync (step 4c.5).

**Infrastructure fixes applied 2026-03-04 (P0):**
- Killed stuck snapraid processes, removed stale lock, fixed stale content file
- Rewrote snapraid_daily/weekly/check_for_deletes with timeouts and alerting
- Added check_snapraid_freshness (daily 8:30am) and check_mergerfs_health (every 15min) to root crontab
- Fixed `MAILTO=""` suppression in root crontab, removed cronic wrapper from snapraid jobs
- Fixed sendmail-system (netcat→curl) — ALL prior email alerts were silently dropped
- Rewrote /etc/smartd.conf: 18 drives pinned by stable ata-ID paths, monthly self-tests
- Root cause of May–Dec sync gap identified (interrupted sync + MAILTO="" suppression)
