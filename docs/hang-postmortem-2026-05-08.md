# System Hang — Post-Mortem

**Date**: 2026-05-08
**Hang detected**: between 07:30 and 11:50 PT (user-observed)
**Last journal entry**: 2026-05-08 07:52:09 PDT
**Recovery**: hard power cycle ~12:00 PT, system back up at 12:01:18
**Outage duration**: ~4h09m
**Uptime before hang**: 6d 22h (boot 2026-05-01 09:33)
**Kernel during hang**: 6.8.0-110-generic
**Kernel after reboot**: 6.8.0-111-generic (auto-applied during reboot, unrelated)

## Symptom

System became unresponsive (no SSH, no web). When power-cycled, the journal showed it had stopped writing mid-stream at 07:52:09 with no error, no kernel oops, no shutdown sequence — a clean lockup.

This is the second unexpected reboot in 8 days. The May 1 boot was also unscheduled, indicating a recurring failure mode rather than a one-off.

## Investigation

### What the logs show

The minutes before the freeze were entirely uneventful:

- **07:50:00** — `sysstat-collect` ran successfully (load avg 1.54, mem 15% used, no swap pressure)
- **07:50:01** — `restart_unhealthy_authentik` cron ran cleanly
- **07:51:09, 07:52:09** — routine ntfy heartbeats logged
- **07:52:09** — last entry. No more journal output until reboot.

Cron jobs preceding the hang (`willflix-check-services`, `check_mergerfs_health`, `restart_unhealthy_authentik`) all completed normally. The most recent `willflix-notify` calls were dedup-suppressed INFOs (containers seen as unknown) — fine.

### What the logs don't show (and that's the finding)

| Signal | Result |
|--------|--------|
| Kernel oops, BUG, panic, call trace | None |
| Soft / hard lockup warnings | None |
| Hung task warnings | None |
| OOM-killer | None |
| EDAC / MCE memory errors | None |
| ATA / I/O / SATA errors | None |
| MergerFS / FUSE errors | None |
| Thermal events | None |
| Resource pressure | None — load 0.81–1.54, 54GB free, no swap |

A clean freeze with no warning is consistent with a **hardware-level halt or a kernel hang that locks the I/O subsystem before the journal can flush**.

### The watchdog that didn't bark

The hardware watchdog was armed (configured on 2026-05-01 in commit `b2760b2`):

```
/willflix/etc/systemd.conf.d/watchdog.conf
  RuntimeWatchdogSec=60
  RebootWatchdogSec=10min
```

Backed by the `nct7904` chip's i2c-attached watchdog. It should have rebooted the system within ~1 minute of the hang. **It did not** — the system stayed dead for 4+ hours.

This was foreshadowed in the journal:

```
May 03 23:55:43 lafayette systemd[1]: Failed to ping hardware watchdog: Connection timed out
May 04 13:17:42 lafayette systemd[1]: Failed to ping hardware watchdog: No such device or address
May 04 14:59:02 lafayette systemd[1]: Failed to ping hardware watchdog: Connection timed out
May 04 14:59:02 lafayette systemd[1]: Failed to ping hardware watchdog: Device or resource busy
May 06 00:23:15 lafayette systemd[1]: Failed to ping hardware watchdog: Connection timed out
```

The `nct7904` watchdog driver path was already known-flaky before this incident. Repeated i2c timeouts pinging the watchdog are a strong tell that the watchdog cannot be relied on as a recovery mechanism. When the kernel actually needed it, it failed.

The NMI watchdog also did not panic, consistent with a halt low-level enough that the NMI handler couldn't run (e.g., bus-stuck, CPU caught in a tight loop with interrupts disabled, or hardware fault).

## Root Cause

**Undetermined.** With zero log evidence we can only narrow probability:

1. **Most likely** — Hardware-level fault on aging Sandy Bridge platform (~2012 vintage). Symptom matches: instant lockup, no MCE survived, sensor-bus watchdog also dead.
2. **Possible** — i2c bus deadlock involving the `nct7904` watchdog driver path. Pre-existing watchdog ping failures show this code path occasionally hangs; a kernel thread holding i2c locks could cascade.
3. **Less likely** — Kernel bug in 6.8.0-110. Nothing in changelog jumps out for hangs without traces.

We do not have enough information to act on root cause directly. The action plan is therefore focused on **detection and recovery** so the next occurrence produces evidence and self-resolves quickly.

## Problems Identified

### P1: Hardware watchdog (`nct7904`) is unreliable

Pre-incident logs show repeated i2c timeouts pinging the watchdog. When the system hung for real, the watchdog did not fire. This is not a watchdog at all if it can't be trusted to trigger.

### P2: No kernel-level reboot-on-fault configuration

`kernel.panic_on_oops`, `kernel.panic`, `kernel.hung_task_panic` were all defaults (no auto-reboot). For an unattended box, a kernel oops should reboot promptly so service is restored even when the human isn't watching.

### P3: No mechanism to capture evidence from the next hang

If this happens again with the same lack of logging, we'll be in the same position. We need pstore / kdump / netconsole to survive a freeze and tell us what was on the CPU at the moment it died.

### P4: No alerting on the prior watchdog-ping failures

`Failed to ping hardware watchdog` warnings appeared in the journal three days before the hang and nothing surfaced them. A reliable monitoring path should have flagged "your safety net is broken" immediately.

## Action Plan

### Immediate (done in this session)

- [x] **Switch watchdog to `softdog`**:
    - `/willflix/etc/modules-load.d/softdog.conf` — load `softdog` at boot
    - `/willflix/etc/udev/rules.d/60-watchdog-softdog.rules` — pin stable `/dev/softdog` symlink to the Software Watchdog
    - `/willflix/etc/systemd.conf.d/watchdog.conf` — `WatchdogDevice=/dev/softdog`
    - softdog won't save us from a hardware freeze, but it doesn't depend on the i2c bus and reliably fires for kernel-level hangs (which is the hung-task path we'll now also panic on).
- [x] **Reboot-on-fault sysctls** (`/willflix/etc/sysctl.d/10-panic.conf`):
    - `kernel.panic_on_oops = 1` — oops triggers panic
    - `kernel.panic = 10` — panic auto-reboots after 10s
    - `kernel.hung_task_panic = 1` — hung task triggers panic
    - `kernel.hung_task_timeout_secs = 300` — 5 minutes
- [x] **Extended `rebuild-lafayette`** to deploy `etc/modules-load.d/` and `etc/udev/rules.d/`.
- [x] **Applied live** without reboot. Verified: `systemd[1]: Using hardware watchdog 'Software Watchdog', version 0, device /dev/softdog`.

### Short-term (open)

- [ ] **Capture evidence on next hang**: enable kdump (or netconsole if a UDP sink is available). Without this, a recurrence will leave us no better off.
- [ ] **Surface watchdog-ping failures**: add a check to `willflix-check-services` (or similar) that greps `journalctl -k --since '24h ago'` for "Failed to ping hardware watchdog" and alerts. Even with softdog, if pings start failing again that's a leading indicator.
- [ ] **Check IPMI/BMC**: this is server-class Sandy Bridge — likely has IPMI. If `ipmitool` is installed and the BMC is reachable, the SEL log may have hardware-level events the kernel never saw. Worth a one-time inspection.
- [ ] **Prophylactic weekly reboot**: while we lack repro signal, bound the exposure. Schedule a reboot every 7d during a quiet window.

### Medium-term

- [ ] **Plan a hardware refresh**. Sandy Bridge is end-of-life. Two unexplained hangs in 8 days on aging hardware is a signal, not a coincidence. Replacing the host (or at least confirming this isn't a faulty DIMM via memtest86+ on a maintenance window) should move up the queue.

## Files Changed

- `etc/modules-load.d/softdog.conf` (new)
- `etc/udev/rules.d/60-watchdog-softdog.rules` (new)
- `etc/sysctl.d/10-panic.conf` (new)
- `etc/systemd.conf.d/watchdog.conf` (added `WatchdogDevice=/dev/softdog`)
- `bin/rebuild-lafayette` (deploys the two new directories)
