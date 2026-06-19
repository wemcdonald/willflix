# Hang Remediation — On-Site Runbook

**Prepared**: 2026-06-15 (remote session). **Execute**: when physically at lafayette.
**Why on-site**: every step below can require a hard power-pull if it goes wrong, and
during a freeze the **power button does not work** (must physically disconnect power) —
so remote KVM/IPMI power control is not a reliable safety net here. Do these with hands
on the box.

Context docs: `hang-investigation-2026-06-15.md` (evidence), `hang-postmortem-2026-05-08.md`
(first incident). Leading hypotheses: **power-delivery sag under peak drive load** and/or
**thermal under load** (fans were moved off the MB to a manual analog controller). Both
fit the freeze pattern (clusters during 01:00 snapraid sync + morning backups) and the
dead-power-button symptom (a power/board wedge takes the BMC down with it).

---

## Pre-work (do remotely / before going on-site)
- [x] IPMI SEL exported (`log/ipmi-sel-2026-06-15.txt`) and cleared — next hardware/PSU
      event will now be recorded cleanly.
- [x] `log-thermals` cron live — CPU temp + load every minute, IPMI voltages/PSU/draw
      every 5 min → `log/thermal.log`. **Before the trip, read the rows around the last
      freeze-time window (01:00) to see whether temps climbed or a rail/PSU went bad.**
- [ ] Pull the latest `log/thermal.log` and grep the 00:55–01:15 rows after the next
      sync; that likely tells you thermal-vs-power before you even open the case.

## Step 1 — Recovery (REVISED 2026-06-16 after failed 4-sec force-off)

**Primary recovery is now an EXTERNAL AC power controller, not a watchdog.** During a hang
even a 4-second power-button hold fails — the BMC/control plane dies with the system, and
only disconnecting AC recovers it. Therefore:
- [ ] **Install a networked/switched PDU or smart outlet** on lafayette's AC, with a
      **ping/heartbeat watchdog from another always-on host**: no response for N minutes →
      cut AC and restore. This is the ONLY recovery that matches "only pulling AC works."
- [ ] The **BMC IPMI watchdog below is now LOW priority** — if the BMC wedges (which the
      failed force-off shows it does), its watchdog can't fire, same as softdog/nct7904.
      Still worth setting up as a secondary for OS-only hangs, but do not rely on it.
- [ ] Also update **BMC firmware** (3.48, old) and investigate the flaky `nct7904`/i2c
      sensor path as a possible BMC-hang trigger (see Step 6 / Step 3).

### Step 1b — IPMI/softdog watchdog (secondary, was Step 1)
Root finding: `softdog` is **deny-listed by Ubuntu's stock HWE blacklist**
(`/usr/lib/modprobe.d/blacklist_linux-hwe-6.8_*.conf`) so it has never loaded since
May 8. And the kernel **IPMI watchdog can't register** because `nct7904` already owns the
legacy `/dev/watchdog` misc node: `IPMI Watchdog: Unable to register misc device`.

Preferred: drive the **BMC IPMI watchdog** (independent of a halted CPU). Resolve the
device conflict first:
1. Stop `nct7904` from claiming the watchdog node — blacklist its watchdog (or the whole
   `nct7904` module; we only used it for sensors that now read garbage anyway):
   `echo 'blacklist nct7904' > /etc/modprobe.d/blacklist-nct7904.conf`
2. Load IPMI watchdog at boot with a hard action:
   `/etc/modules-load.d/ipmi-watchdog.conf` → `ipmi_watchdog`
   `/etc/modprobe.d/ipmi-watchdog.conf` → `options ipmi_watchdog timeout=120 action=power_cycle nowayout=0 panic_wdt_timeout=0`
   (`power_cycle`, not `reset` — a wedged board may ignore a warm reset.)
3. Point systemd at it: `/etc/systemd/system.conf.d/watchdog.conf` →
   `WatchdogDevice=/dev/watchdog` (after nct7904 is gone, the IPMI driver takes the misc
   node), keep `RuntimeWatchdogSec=60`, `RebootWatchdogSec=10min`.
4. Reboot. Verify: `journalctl -b | grep -i 'hardware watchdog'` shows the **IPMI**
   watchdog, and `ipmitool mc watchdog get` shows it **Running / power_cycle / counting**.
5. **TEST IT FOR REAL** (this is the whole point — do it with hands on the box):
   `echo 1 > /proc/sys/kernel/sysrq; echo c > /proc/sysrq-trigger` (forces a panic) — OR
   freeze hard with `echo 0 > /proc/sys/kernel/hung_task_timeout_secs` style stall. Confirm
   the BMC **power-cycles the box within ~2 min unattended**. If it does NOT, the BMC
   itself is unreliable (consistent with the dead-power-button symptom) → see Step 6.
   Keep the panic sysctls (already live and correct).

## Step 2 — Power delivery (PRIME suspect, promoted 2026-06-16)
The box wedges during peak multi-drive load and the power button dies during the hang —
both point at the PSU / power path on a ~14-yr platform. Overnight telemetry strengthened
this and exposed a concrete lead.
- [ ] **Restore PSU redundancy (do this first — cheapest mitigation + diagnostic).**
      Current state: chassis is a SC846E16-R1200B (1+1 redundant cage), but only a single
      **PWS-920P-SQ** (quiet) module is installed — second bay intentionally empty for
      noise, which is why IPMI only sees `PS2`. The original matched **PWS-1K21P-1R** 1200W
      pair was pulled for noise (NOT because faulty) and is retained.
      - Reinstall the **matched original 1200W pair** → real 1+1: load-sharing halves the
        current per module, either covers a transient sag, and the BMC resumes reporting
        PS1/PS2 + redundancy/AC-fail SEL events (telemetry we currently lack).
      - **Matching constraint: do NOT mix the 920-SQ with a 1200W module** — redundant
        modules must be the same model to share. Run a matched pair (both 1200W, or two
        920-SQ).
      - This is a *test*: if freezes stop with the redundant pair in, power is confirmed →
        then source a **second PWS-920P-SQ** for a quiet matched pair as the permanent fix.
      - Capacity is NOT the issue (920W ≫ ~500W load); this is about failover + isolating a
        flaky single unit, not watts.
- [ ] Reseat: PSU connectors, ATX 24-pin + EPS 8-pin, all SATA power splitters.
- [ ] **IPMI voltage telemetry is dead** — every rail reads "No Reading", so you CANNOT
      diagnose this from logs. Use a **multimeter / PSU load tester** on the 12V/5V/3.3V
      rails under load (kick off a snapraid sync while measuring).
- [ ] **Measure the +5VSB standby rail specifically.** The failed 4-sec force-off points at
      a standby/control-plane collapse; a sagging 5VSB (aging-cap failure in the PSU standby
      section) would take down both the OS and the BMC. This is now a prime physical check.
- [ ] **2026-06-18 refinement — it's the DISK-ACTIVITY ONSET, not CPU.** The box froze again
      ~3 min into the 01:00 snapraid run with CPU throttled, load only ~3.0, temps flat. The
      trigger is drives spinning up + initial multi-drive reads → a **12 V spin-up inrush**
      (~250–340 W) on the single PSU. The matched 1200 W pair directly addresses this (2× 12 V
      headroom). When measuring, watch the **+12 V rail at the moment snapraid wakes the
      drives** (`sudo /willflix/bin/cron/snapraid_daily`).
- [ ] **Already running (no case needed):** spin-down disabled on all SATA HDDs so the 01:00
      run no longer mass-spins-up the array (isolation test). Permanent fix if confirmed:
      enable **staggered drive spin-up** on the SAS backplane/HBA, or keep the no-spindown
      rule. (`etc/udev/rules.d/69-hdparm-nospindown.rules`.)
- [ ] Load-test or swap the PSU. With 11+ data + 3 parity drives spinning up under
      snapraid, peak draw is high; a degraded PSU sags. **Strongly consider a fresh PSU**
      regardless — cheap relative to the outages.
- [ ] Check the analog fan controller wiring while in there (see Step 3).

## Step 3 — Thermal / fans
Background: dynamic IPMI fan control was attempted and never worked; case fans were
unplugged from the MB and put on a **manual analog controller**. Empty MB fan headers are
why `nct7904`/IPMI report fan garbage (FANA 19125 RPM then 0) — that's **expected**, not
an i2c fault. But it means fan speed is now manual and unverified.
- [ ] With the case open under load, confirm CPU/case fans actually spin at adequate RPM;
      turn the analog controller up.
- [ ] If `log/thermal.log` showed CPU pkg temps climbing toward 81/91 °C crit during the
      sync → reseat heatsinks + repaste (14-yr-old TIM is likely dried out).
- [ ] Optional: get IPMI fan control working so the BMC manages cooling and re-reports
      real RPM (then `nct7904` garbage goes away). Lower priority than power/watchdog.

## Step 4 — Memory (currently a blind spot)
EDAC failed to bind (`EDAC sbridge: Seeking for PCI ID 8086:3ca0 …` loops) so corrected/
uncorrected DIMM errors are **invisible to the OS**. A bad DIMM would silently freeze.
- [ ] Boot **memtest86+** and run ≥1 full pass (overnight) — rules RAM in or out cleanly.
- [ ] Install `rasdaemon`; investigate EDAC sbridge binding (may need `edac_core` /
      `sb_edac` vs `skx_edac`, or a kernel param) so future DIMM errors are logged.

## Step 5 — Evidence capture for any future freeze
- [ ] Enable **kdump** (reserve `crashkernel=` on the kernel cmdline → reboot → test with
      a forced SysRq crash, same as Step 1.5). `/var/crash` is currently empty.
- [ ] Optional **netconsole** to a UDP sink on another always-on host — only helps if the
      freeze produces any kernel output (these have been silent, so low yield).

## Step 6 — BMC health
The BMC firmware is **3.48** (old). The dead-power-button-during-hang symptom suggests the
BMC may be wedging along with the board.
- [ ] Update Supermicro BMC firmware.
- [ ] Confirm `ipmitool chassis power cycle` works from another host while the OS is up
      (baseline), so remote recovery is at least possible between freezes.

## Step 7 — Bound exposure
- [ ] Once the Step 1 watchdog is **validated**, add a prophylactic weekly reboot in a
      quiet window (e.g. Sun 05:00, after the weekly scrub) to cap uptime drift.
- [ ] Add the watchdog-ping-failure alert the May 8 plan specified (grep journal for
      "Failed to ping hardware watchdog").

## Step 8 — Strategic (already in motion)
Hardware sizing for a replacement MB/CPU/RAM is already underway
(`docs/hardware-sizing-2026-06.md`, `log_plex_capacity` sampler). This is the real fix:
~14-yr-old Sandy Bridge with ~5 unexplained freezes in 6 weeks. Steps 1–7 buy reliable
recovery + evidence in the meantime; they are not a cure.
