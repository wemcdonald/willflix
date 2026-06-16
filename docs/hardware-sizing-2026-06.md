# Lafayette Hardware Sizing — Workload Analysis (June 2026)

Goal: decide what MB / CPU / RAM to buy to replace the 2012 dual-Xeon E5-2620.
The user's working assumption was "I use lots of RAM (transcode ramdisk) and lots
of CPU cores." **The data says otherwise.**

## Method

Two existing data sources, no new tooling needed for the verdict:
- **Tautulli** (`appdata/tautulli/config/tautulli.db`) — 165 days of Plex play history.
- **sysstat / sar** (`/var/log/sysstat/`) — ~18 days of system CPU/load samples.

(Plus a new sampler added for transient confirmation — see Instrumentation below.)

## Findings

| Metric | Measured (165 days) | Limiting factor? |
|---|---|---|
| RAM used (system) | 7.4 GB of 62 GB; 54 GB free | **No — 2–3× oversized** |
| Transcode ramdisk (`/Volumes/PlexTranscode`, 20 GB tmpfs) | ~5 transcodes peak ≈ <2 GB resident | No |
| Peak concurrent streams (ever) | **10** | — |
| Peak concurrent **transcodes** (ever) | **5** | — |
| Streams that transcode | 26% (1223/4736); rest direct play | — |
| **4K transcodes** (the CPU killer) | **2, ever** | — |
| Transcode source res | almost all 1080p / 720p | — |
| Plays/day (last 30d) | ~30 | — |
| Peak system CPU (sar) | **~38%**, and those peaks are 1–3am snapraid/backups, not Plex | **No — never saturated** |

### Verdict
- **Neither RAM nor core count is the constraint.** Both are heavily over-provisioned.
- The real deficiency is the **lack of hardware transcoding**: the E5-2620 has no
  Quick Sync and the only GPU is a Matrox BMC chip, so every transcode is brute-forced
  in software. A single modern Intel iGPU (UHD 730/770) does the entire measured peak
  (5× 1080p) at near-zero CPU and a fraction of the wattage.
- Dual E5-2620 idles ~100–150 W; a modern chip idles ~15–30 W → meaningful OPEX over
  years of 24/7 uptime.

### Relationship to the hang investigation
The server "trouble" is being tracked separately in
[`hang-investigation-2026-06-15.md`](hang-investigation-2026-06-15.md) (freezes under
load; thermal/PSU/voltage sampling via `log-thermals`). That points at the **aging 2012
platform itself**, not insufficient capacity — which *reinforces* replacing the hardware,
but means the replacement does **not** need to be large.

## Recommendation (summary)

Buy a modern Intel chip with **Quick Sync** (UHD 730/770+), a board with **one free
PCIe x8-electrical slot** for the existing LSI HBA (SATA port count irrelevant — HBA
handles the 14 drives), and **start at 32 GB**, leaving DIMM slots open to grow.

**2026 twist:** RAM is the most expensive line item (AI/HBM-driven DRAM squeeze).
DDR4 32 GB is ~30–40% cheaper than DDR5 and LGA1700 is a dead-end socket either way,
so a **DDR4 LGA1700 board is the smart money**. Skip AM5 (weaker iGPU transcoding,
forces DDR5), W680/ECC (unjustified given SnapRAID parity), and LGA1851 (forces DDR5 +
immature Arrow Lake Plex Linux transcoding).

→ **Full build options, part numbers, prices, and verdicts:**
[`hardware-upgrade-options-2026.md`](hardware-upgrade-options-2026.md).
Headline pick: **i5-13500 + B760 DDR4 + 32 GB DDR4 ≈ $520–570, ~15–25 W idle.**

## PSU sizing (elevated to a first-class spec)

The hang investigation ([`hang-onsite-fix-plan-2026-06-15.md`](hang-onsite-fix-plan-2026-06-15.md))
names **power-delivery sag under peak drive load** as the prime suspect: freezes cluster at
01:00 snapraid (all 14 drives active) and the power button dies during the hang (board/BMC
wedge). That reframes the PSU as a reliability-critical component for the new build — and
further de-prioritizes compute (the failure is power/platform, not capacity).

Power budget (new platform + the existing 14 HDDs = 11 data + 3 parity):

| Component | Steady | Spin-up surge (12V) |
|---|---|---|
| i5-13500 (PL2 peak ~154W; real workload <65W) | ~50–65W | — |
| Board + 32GB + fans | ~35–45W | — |
| LSI HBA | ~15W | — |
| Boot SSD | ~3W | — |
| 14× 3.5" HDD @ ~8W run / ~24W spin-up | ~110W | **~350–420W** |
| **Total** | **~230–250W** | **~460–480W peak (few sec)** |

Two sizing drivers:
- **Steady ~250W** → size so this is ~40–50% load (efficiency/longevity band) → ~500–550W.
- **Simultaneous spin-up surge** is the real event — ~28–35A on +12V from drives alone.
  This is the exact "peak multi-drive load" the hang plan blames; a tired 14-yr-old PSU sags here.

**Recommendation:**
- **Minimum: 550W, 80+ Gold, single +12V rail** (~45A on 12V; efficient at steady load).
- **Recommended: 650W 80+ Gold** (~54A on 12V; room for 2–4 more drives). ~$90–120
  (Seasonic / Corsair RM / be quiet).
- Don't go below 550W; don't overbuy 850W+ (inefficient at ~250W load).
- **Single 12V rail** for many-drive builds (avoids per-rail OCP tripping on spin-up).
- **Enable staggered spin-up on the HBA** — turns the surge into a non-event; cheapest reliability win.
- Quality > wattage: the hangs suggest a *degraded* PSU, so a fresh Gold unit with a strong
  single 12V rail addresses the suspected root cause independent of the platform swap.

Caveat: assumes ~8W idle / ~24W spin-up consumer drives. If any are 7200rpm enterprise units
(~12W idle / ~30W spin-up), prefer the 650W pick. Drive models not yet confirmed.

## Instrumentation added (to confirm transients before buying)

sar averages over 10-min windows, so it *could* mask brief CPU spikes during a
multi-transcode burst. To nail the real numbers, a passive sampler now runs every 2 min:

- **Script:** `bin/cron/log_plex_capacity` (raw sampler, not wrapped in `willflix-cron`,
  matching the `log-thermals` precedent; exits 0, never alerts).
- **Cron:** `*/2 * * * *` in `etc/root-crontab`.
- **What it records** (per run, to a *persistent* CSV — not the weekly-rotated `*.log`):
  instantaneous CPU%, load1, RAM used, **active transcode count** (`Plex Transcoder`
  process count), and **transcode-ramdisk used MB/%**.
- **Outputs:**
  - `log/plex-capacity/metrics.csv` — time series (8 columns, header row).
  - `log/plex-capacity/peaks.txt` — all-time high-water-marks: `max_transcoders`,
    `max_ramdisk_mb`, `max_cpu`, `max_cpu_txc` (peak CPU *while* transcoding).

### How to read it (after ~1–2 weeks)
```bash
cat /willflix/log/plex-capacity/peaks.txt          # the numbers that matter for sizing
# busiest moments:
sort -t, -k6 -rn /willflix/log/plex-capacity/metrics.csv | head    # by transcode count
sort -t, -k3 -rn /willflix/log/plex-capacity/metrics.csv | head    # by CPU%
```
Interpretation: if `max_ramdisk_mb` stays well under ~8000 and `max_cpu_txc` stays
modest, 32 GB RAM + a mid Quick Sync chip is confirmed more than enough. If a real
transcode burst ever pushes CPU near saturation, bump one CPU tier.

### Cleanup when done
Remove the `*/2 * * * * .../log_plex_capacity` line from `etc/root-crontab`
(then `sudo crontab /willflix/etc/root-crontab`). Optionally keep the CSV for reference.
