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
