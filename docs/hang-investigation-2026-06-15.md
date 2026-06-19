# System Hang — Follow-up Investigation

**Date**: 2026-06-15
**Author**: diagnosis session
**Predecessor**: `docs/hang-postmortem-2026-05-08.md`

## TL;DR

The hangs did **not** stop after the May 8 remediation. The system has frozen
**at least 4 more times** since (May 21, Jun 9, Jun 15), and the May 8 recovery
mechanism (`softdog`) **never actually loaded on any boot** because it is
deny-listed by Ubuntu's stock HWE-kernel blacklist. Every freeze since May 8 has
been running on the flaky `nct7904` watchdog the postmortem tried to abandon.

## Update — refined picture (later in same session, with owner context)

Two facts from the owner reframed the diagnosis:

1. **Fans were rewired to a manual analog controller** (after an earlier failed attempt at
   IPMI dynamic fan control). So the empty MB fan headers are why `nct7904`/IPMI report
   fan garbage (FANA 19125→0 RPM) — that is **expected**, not evidence of i2c instability.
   But fan speed is now manual/unverified → thermal-under-load is plausible and unmonitored.
2. **During a hang the power button does nothing** — the box must be physically unplugged;
   remote KVM/IPMI power does not recover it. That means the freeze wedges the **power
   path / BMC**, not just the OS.

### Load correlation (freeze times vs root crontab)
- **2026-05-21 01:12** and **2026-06-15 01:03** froze **3–12 min into the 01:00
  `snapraid_daily` sync** — 11 data + 3 parity drives spun up, heavy CPU parity calc.
- **2026-05-08 07:52** and **2026-06-09 07:15** — morning window (likely
  `backup_google_photos` from will's crontab; confirm its schedule).
- Net: freezes cluster in **peak disk-I/O / sustained-load windows**, not at random.

### Ranked hypotheses (current)
1. **Power-delivery sag under peak drive load.** 14 drives spinning + old PSU →
   12V/5V rail sag → board brownout/wedge. Fits load timing AND dead-power-button (a power
   wedge takes the BMC with it). *Test:* IPMI rail voltages now logged every 5 min; SEL
   cleared to catch PSU/voltage events; reseat/swap PSU on-site.
2. **Thermal under load.** Manual analog fans may be too slow; sustained snapraid load
   heats CPU/VRM → trip. Idle temps are cool (~40 °C, crit 91) but load temps were
   unobserved. *Test:* `log-thermals` now captures CPU pkg/core temp every minute.
3. **Bad DIMM.** Parity calc is memory-heavy; EDAC can't bind so DIMM errors are invisible.
   *Test:* memtest86+ on-site; install rasdaemon.
4. **i2c/SATA controller hang under load** — lower now that fan garbage is explained.

### Watchdog can't be fixed remotely (new finding)
The kernel **IPMI watchdog fails to register**: `IPMI Watchdog: Unable to register misc
device` — `nct7904` already owns the legacy `/dev/watchdog` misc node. Bringing up the BMC
watchdog requires blacklisting nct7904 + a reboot to reorder, then a **forced-hang test**
to prove it power-cycles. That belongs on-site (see `hang-onsite-fix-plan-2026-06-15.md`).

### Actions taken this session (safe, remote, evidence-only)
- Exported + cleared the overflowed IPMI SEL (`log/ipmi-sel-2026-06-15.txt`).
- Added `bin/log-thermals` + a temporary `* * * * *` root-cron entry → `log/thermal.log`
  (CPU temp/load every min, IPMI voltages/PSU/draw every 5 min). Remove after diagnosis.
- Confirmed BMC healthy *now* (power on, no faults, restore policy `previous`).
- Did **not** change watchdog/boot config remotely (deferred to on-site runbook).
- **Load mitigation**: added `bin/cron/snapraid-throttled` (caps CPU to 1.8 GHz + disables
  turbo + `nice`/`ionice` for the duration of the run, restores on exit) and routed
  `snapraid_daily` sync and `snapraid_weekly` scrub through it. Shaves the peak power/heat
  during the 01:00 window that 2 of 4 freezes occurred in, without affecting daytime Plex
  performance or parity protection. Verified cap engages mid-run and restores after.
  Reversible: revert the two call sites + delete the wrapper.

### Note on diagnosis interaction
Throttling lowers freeze probability *and* slightly lowers the load the logger captures —
but if the box **still freezes while throttled**, that's strongly informative (points away
from a simple raw-load → power/heat threshold). If freezes stop, load is confirmed as the
trigger. Either outcome advances the diagnosis.

## 2026-06-19 — root SSD SATA dropout (a DIFFERENT failure mode); EDAC now works

The 06-18 18:59 event was **not** a classic total freeze. Owner clarified: **SSH still
worked, but every command failed with disk errors** → kernel + network stayed alive while
the **root SSD dropped off the SATA bus**. Journald stopped at 18:59 because it couldn't
write to an erroring root. Appeared ~2.5h after the PSU swap (done at the ~14:00/16:25 Jun 18
reboot). This is a SEPARATE failure mode from the total freezes (where SSH is dead).

Evidence (root SSD = Samsung 860 EVO on `ata4`, a native onboard **3 Gbps** port — so the
3.0 Gb/s link is normal, NOT a downshift; the 6 Gbps ports came up at 6.0):
- SMART healthy: PASSED, 0 reallocated/pending/uncorrectable, 0 lifetime CRC; error log clean.
- **SATA PHY log: 2× PhyRdy→PhyNRdy + 2× COMRESET, 0 CRC/R_ERR** → the link went down
  *cleanly* (no signal corruption). A bad DATA cable shows CRC errors; a clean link-loss
  points at **power or a physical connection** → most likely the **new PSU's SATA power lead
  or a connector disturbed in the swap**.
- Caveat: PHY counters are lifetime, not timestamped (2 drops total) — suggestive, not proof;
  the real errors were lost when root went unwritable.

**Action:** reseat the SSD's SATA data + power, use a different SATA power lead off the new
PSU, ideally a known-good data cable. PHY baseline to re-check later: PhyRdy→PhyNRdy=2,
COMRESET=2 — if these climb, the link is still dropping (→ suspect SATA power lead or the
onboard controller).

**Also note:** snapraid was disabled yet the box still had problems → snapraid was never the
cause (01:00 clustering was coincidental). And **EDAC now BINDS** (`sb_edac` registered both
controllers; was failing on 06-15) → ECC memory errors are finally observable → rasdaemon.

**Two distinct problems now:**
1. Recurring **total freezes** (SSH dead, BMC dead) — board/VRM/CPU or bad DIMM; top
   diagnostic **memtest86+** (on-site) + reseat RAM; **EPCR2** for recovery.
2. **Root SSD SATA dropout** (SSH alive) — power/connection to the SSD; reseat + reroute as
   above. Likely introduced around the PSU swap.

## 2026-06-18 — froze AGAIN; throttle didn't help; trigger = disk-onset

Froze **01:03:31**, ~2.5 days uptime; manual restart 16:25. **Third crash at ~01:03–01:12**
— squarely in the 01:00 `snapraid_daily` window (also May 21, Jun 15). thermal.log:

```
01:00 load 0.77 temp 39   01:02 load 2.02 temp 40
01:01 load 1.53 temp 39   01:03 load 3.02 temp 41  <- last sample, dead ~30s later
```

- **CPU throttle did NOT prevent it, and load was only ~3.0 (just ramping) with temps flat
  39–41 °C.** So it is NOT CPU power, NOT sustained load, NOT thermal — confirmed dead.
- It froze at the **onset of disk activity** — snapraid spinning up idle drives + starting
  to read all of them. New lead hypothesis: **drive spin-up power transient** (11–14 drives
  drawing ~2 A each on 12 V simultaneously ≈ 250–340 W inrush) sagging the single PSU; or a
  SATA/SAS controller/backplane fault on I/O onset.
- **SEL (first crash since the 06-15 clear) captured nothing useful** — a timestamp-less
  "Pre-Init Unknown #0xff" marker (weakly corroborates a board power event) + the restart's
  chassis-intrusion. No PSU/voltage event **because the BMC voltage sensors are dead, so it
  literally can't log a sag.** BMC clock was UTC; set to local 06-18 for future correlation.

### Mitigation/test running (no case-open needed)
Disabled spin-down on all SATA HDDs (`hdparm -S 0 -B 254`, live + persistent udev rule
`etc/udev/rules.d/69-hdparm-nospindown.rules`) so the 01:00 run no longer triggers a mass
simultaneous spin-up. **If freezes stop → spin-up transient confirmed. If it still freezes →
points at sustained multi-drive I/O / controller, not spin-up.** Either way, isolating.

### Hypothesis ranking (post-06-18)
1. **Power delivery at disk-activity onset** — spin-up 12 V inrush on a single aging PSU.
   Restore the matched 1200 W redundant pair (2× headroom + failover) = top on-site action.
2. **SATA/SAS controller / backplane / HBA fault** on I/O onset.
3. **Bad DIMM** (EDAC blind) — memtest on-site.
4. ~~CPU / thermal / sustained load~~ — ruled out (throttled + flat temps + low load).

## 2026-06-16 — KEY: 4-second force-off also fails

Confirmed with owner: during a hang, **even a 4-second power-button hold does not power
the box off** — only physically disconnecting AC recovers it. The 4-sec force-off is
handled by the BMC / board power-sequencing on **standby power (5VSB), independent of the
CPU/OS**. So whatever kills the system **also kills the BMC/control plane** — they share
fate, and only a full AC/standby reset clears it.

**This re-ranks everything:**
- **Down (BMC survives these on standby and would force-off):** bad DIMM ~5–10%, storage
  controller / CPU lockup ~5–10% each, kernel/software ~nil.
- **Up (take OS + BMC down together):** standby/5VSB power collapse (failing PSU standby
  section or board — classic aging-cap failure), i2c-bus deadlock hanging the BMC (the
  nct7904 sensor bus is known-flaky and the BMC masters it), or board-level latch-up.
- Combined power/control-plane: **~75–85%**. PSU-module swap actually fixes it **~30–35%**.
  BMC/board control-plane (incl. i2c-induced BMC hang, FW 3.48) **~20–30%**.

**Consequence for recovery — the BMC watchdog plan is likely useless here.** If the BMC
wedges, its own watchdog can't fire (same reason softdog/nct7904 can't). The only recovery
that fits "only AC removal works" is **external AC power control**: a networked/switched
**PDU or smart outlet** driven by a ping/heartbeat watchdog from another always-on host —
no ping for N minutes → cut + restore AC. This supersedes Step 1 of the on-site runbook as
the recovery mechanism. Restoring the redundant PSU still helps a standby-rail fault (5VSB
outputs are diode-OR'd → standby gets redundancy too).

## Overnight 2026-06-16 — first data after changes

Ran the (now throttled) 01:00 `snapraid_daily` sync; box **did not freeze** (up 21h).
What the telemetry showed:

- **Thermal: essentially ruled out.** CPU held **38–42 °C** the whole time, including the
  load ramp to 6.0 at 01:05–01:20 (crit is 91 °C). Cooling is adequate even under sync
  load. (Caveat: this was the throttled run; but the flatness is decisive enough to
  down-weight thermal hard.)
- **Power telemetry is DEAD.** Every IPMI voltage rail (VTT, Vcore, all VDIMM, +1.1/1.5/
  3.3/5/12 V, VBAT) reads **"No Reading"**. We **cannot detect a rail sag in software** —
  the power-sag hypothesis can now only be tested **physically on-site** (multimeter / PSU
  load test). This is the single biggest gap.
- **Running a single PSU by choice.** Chassis is SC846E16-R1200B (1+1 redundant cage) but
  only one **PWS-920P-SQ** (quiet) module is installed — second bay left empty for noise
  (which is why IPMI only sees `PS2`). The original matched **PWS-1K21P-1R** 1200W pair was
  pulled for noise, not failure, and is retained. So there's currently **no failover**: any
  transient sag/glitch on the single module crashes the box. 920W is ample capacity (~500W
  load) so this isn't watts — but restoring a *matched* redundant pair (load-share +
  failover + PSU telemetry) is the top on-site action. Don't mix 920-SQ with 1200W.
- SEL still clean (0 entries), no kernel warnings overnight. Throttle engaged then restored
  correctly (`no_turbo` 0, max_freq 2.5 GHz now). snapraid completed (freshness stamp set).

**Do not over-read the clean night.** Only ~2 of ~38 nightly syncs froze (~5%/night), so a
single quiet night is ~95% likely even with no fix — it proves nothing about the throttle.
The value last night was the telemetry, not the survival. Need 1–2 weeks of clean windows
to say the mitigation helped.

### Revised hypothesis ranking (post-overnight)
1. **Power delivery** (now clear lead) — and we have a concrete lead: `PS1` absent/failed on
   a dual-PSU board; fits load-timing + dead-power-button. Telemetry can't confirm → on-site.
2. **Bad DIMM** — still open (EDAC blind); memtest on-site.
3. ~~Thermal~~ — down-weighted to unlikely (temps flat and cold under load).

## Confirmed freeze timeline (from `journalctl --list-boots`)

| Boot ended (last journal line) | Recovered (next boot) | Down | Signature |
|---|---|---|---|
| 2026-05-08 07:52:09 | 12:01:18 | ~4h | clean freeze (documented) |
| 2026-05-21 01:12:17 | 17:46:18 | ~16.5h | clean freeze — last line mid-stream ntfy heartbeat, no shutdown |
| 2026-06-09 07:15:41 | 09:56:46 | ~2.6h | clean freeze |
| 2026-06-15 01:03:17 | 11:33:12 | ~10.5h | clean freeze |

All recoveries were **manual power cycles** — no watchdog fired. Every boot ends
mid-stream on a routine `ntfy` stats line with no shutdown sequence: identical
clean-lockup signature to May 8. Two of four cluster around the **01:00 cron /
snapraid window**; the others are early-morning (07:15/07:52). Frequency: roughly
every 1–3 weeks and not obviously slowing.

## Why recovery never worked

1. **`softdog` is deny-listed.** Journal this boot:
   `systemd-modules-load[612]: Module 'softdog' is deny-listed`. Source:
   `/usr/lib/modprobe.d/blacklist_linux-hwe-6.8_6.8.0-111-generic.conf:57`
   (a stock Ubuntu file). The May 8 `etc/modules-load.d/softdog.conf` does not
   override a modprobe blacklist, so softdog has not loaded since May 8. The
   "Verified: Using Software Watchdog" line in the May 8 postmortem reflected a
   live `modprobe` that session — it never survived a reboot.
2. **Active watchdog is still `nct7904`** (i2c). `/dev/watchdog0` (major 244) is
   the nct7904 char device; `WatchdogDevice=/dev/softdog` points at a symlink
   that doesn't exist (softdog absent), so systemd fell back to the flaky chip.
3. Panic sysctls **are** live and correct (`panic=10`, `panic_on_oops=1`,
   `hung_task_panic=1`, `hung_task_timeout_secs=300`) — but a hard hardware
   freeze produces no oops and no hung-task, so they can't fire either.

## New hardware evidence (IPMI / BMC — Supermicro, was never checked before)

- **BMC reachable** via `ipmitool` (Supermicro, FW 3.48).
- **SEL is OVERFLOWED (512 entries, full, wrapping).** Dominated by `nct7904`
  fan-sensor garbage: FANA logged an impossible **19125 RPM** then **0 RPM**
  flapping on 2026-05-08 20:08–20:11. Same i2c sensor chip as the old watchdog →
  the i2c/sensor subsystem is genuinely unstable. Because the SEL is full, any
  real hardware events around the actual freeze moments were pushed out.
- **No MCE/DIMM fault currently visible** — but the SEL overflow makes this
  inconclusive, and see EDAC blind spot below.
- Recent SEL chassis-intrusion entries (05/22, 06/09, 06/15) do **not** align
  with freeze times → unrelated.

## Monitoring blind spots discovered

- **EDAC failed to bind**: `EDAC sbridge: Seeking for PCI ID 8086:3ca0 ...`
  loops — the Sandy Bridge memory-controller EDAC driver never attached, so
  **corrected/uncorrected memory errors are not reported to the OS at all**.
- No `rasdaemon` / `mcelog` installed. `HEST: Firmware First mode` routes
  corrected errors to firmware → the (overflowed) SEL. Net: **a failing DIMM
  would be effectively invisible.** RAM has not been ruled out.
- **kdump still not enabled**; `/var/crash` empty. No crash evidence capture.

## Updated root cause assessment

Still most consistent with a **hardware-level fault on aging Sandy Bridge**
(instant lockup, no MCE/oops survives, i2c sensor bus throwing garbage). The new
data strengthens this: an unstable i2c/sensor subsystem and zero memory-error
visibility on ~14-year-old hardware. A software/i2c-deadlock contribution can't
be excluded, but no software watchdog that depends on a live CPU/timer (softdog,
nct7904) is a reliable recovery for this signature.

## Recommended plan

**The one recovery mechanism that fits a halted-CPU freeze is the BMC's own
watchdog timer** — an independent microcontroller that power-cycles the box
regardless of CPU state. `ipmi_watchdog.ko` is present; BMC watchdog is currently
`Stopped`.

### A. Make recovery actually work (minutes, not hours of downtime)
1. Load `ipmi_watchdog` at boot and point systemd `WatchdogDevice` at it
   (BMC reset-action watchdog). This survives a hard CPU halt; softdog/nct7904
   do not.
2. Either properly override the softdog blacklist (`/etc/modprobe.d`) as a
   secondary, or drop softdog entirely in favour of the IPMI watchdog.
3. Keep panic sysctls (already correct).

### B. Capture evidence on the next freeze
4. **Clear the overflowed SEL now** (`ipmitool sel clear`) so the next hardware
   event is recorded cleanly. (Export it first.)
5. Enable **kdump** + consider **netconsole** to a UDP sink.
6. Install **rasdaemon**; investigate why EDAC sbridge won't bind (may need a
   module option / kernel arg) so DIMM errors become visible.

### C. Bound exposure & rule out RAM
7. Schedule a **prophylactic weekly reboot** in a quiet window (still not done).
8. Add the **watchdog-ping-failure alert** the May 8 plan specified.
9. **memtest86+** on a maintenance window to rule out a failing DIMM.

### D. Strategic
10. **Plan hardware refresh.** Sandy Bridge is ~14 years EOL; this is now ~5
    unexplained freezes in 6 weeks. Recovery automation buys time, not a cure.
