# EPCR2 Setup Plan — external AC power control / auto-reboot for lafayette

**Device**: Digital Loggers **EPCR2** (Ethernet Power Controller II) — 8 individually
switched banks across **two 15 A circuits**. This is the recovery mechanism chosen after we
found that during a hang even a 4-second power-button force-off fails and only an AC pull
recovers the box (see `docs/hang-investigation-2026-06-15.md`). The EPCR2's **AutoPing**
self-recovers the box; the `bin/epcr2-power` script gives manual control from the PiKVM.

Refs: [REST API](https://www.digital-loggers.com/rest.html) ·
[AutoPing](https://www.digital-loggers.com/autoping.html) ·
[EPCR2 FAQ](https://www.digital-loggers.com/epcr2_faqs.html)

## 1. Physical / electrical
- [ ] Mount/place the EPCR2. Plug lafayette's PSU(s) into switched banks.
- [ ] **Stay within one 15 A circuit's limit.** A 24-bay 4U pulls ~6–8 A running but a
      simultaneous spin-up of 24 drives spikes much higher — keep the server on a circuit
      with headroom and avoid sharing it with other big loads.
- [ ] If/when you restore the **dual PSU**: put both PSU feeds on switched banks and record
      their UI outlet numbers — AutoPing and the `server` command must cycle **both together**,
      or the standby (5VSB) rail stays alive on the other PSU and the latch won't reset.

## 2. Network + security (it's an insecure HTTP UI — lock it down)
- [ ] First boot: it defaults to **`192.168.0.100`, `admin/1234`**. Reach it on a laptop,
      then **change the admin password immediately**.
- [ ] Give it a **static IP or DHCP reservation**; record it as `EPCR2_HOST`.
- [ ] **Do not expose it to the internet.** No TLS, weak auth. Keep it on the trusted LAN/
      mgmt segment. Remote access path: **Tailscale → SSH to PiKVM → run `epcr2-power`**
      over the LAN. Optionally firewall the EPCR2 so only the PiKVM's IP can reach it.
- [ ] Disable any DLI **cloud / external relay / "lights-out"** linking you don't use.
- [ ] Under **External APIs**, ensure the **REST API is enabled** for the admin user (DLI
      notes only admin can script by default; you can scope a separate user if preferred).
- [ ] Update **firmware** to current.

## 3. AutoPing (the auto-reboot)
Goal: if lafayette stops answering ping, cut+restore its AC automatically.
- [ ] **AutoPing tab → add IP** = lafayette's primary NIC address (confirm the box actually
      responds to ICMP; AutoPing is ICMP-only).
- [ ] **Link** that IP to lafayette's PSU outlet(s) via the checkboxes (both, if dual PSU).
- [ ] Settings:
  - Ping interval: **~60 s**.
  - Failed pings before action: **5–10** (DLI's recommended range; ~5–10 min of silence).
  - **Cold-boot / power-cycle action** with an **off-time ≥ 30 s** (drains 5VSB → real
    board+BMC reset; this is the whole point for our failure mode). Set via `EPCR2_OFF_SECS`
    equivalent / the device's cycle delay.
  - **Device Reboot Delay** (post-cycle wait before re-checking): **≥ 900 s (15 min)** so it
    waits out a full boot + service start before deciding it failed again.
  - **Max reboot attempts**: **3** — so a genuinely-dead box isn't power-cycled forever
    (after which you'll notice it's down rather than thrashing).
- [ ] **Reboot-loop guard**: the reboot-delay + max-attempts above are what prevent a loop
      during a long fsck/boot or while snapraid is mid-sync. Double-check them.

## 4. Manual control from PiKVM (`bin/epcr2-power`)
- [ ] Deploy the script to the PiKVM (Arch, read-only rootfs):
      `rw` → copy `epcr2-power` to `/usr/local/bin/` → `chmod +x` → `ro`.
- [ ] Create `~/.config/epcr2/config` (chmod 600) per the header in the script: `EPCR2_HOST`,
      `EPCR2_USER`, `EPCR2_PASS`, `EPCR2_SERVER_OUTLETS="1 2"`, `EPCR2_OFF_SECS=30`.
- [ ] Verify: `epcr2-power status`, then `epcr2-power cycle <spare-outlet>` on a non-critical
      load before trusting it on the server.
- Commands: `status` · `on/off/cycle N|all` · **`server`** (cycles all server outlets
  together = full AC reset). Uses the REST API (digest auth + `X-CSRF: x`).

## 5. Test plan (do before relying on it)
- [ ] **Manual**: `status`, `on`/`off`/`cycle` a spare outlet. Confirm states match the UI.
- [ ] **AutoPing dry-run**: temporarily set fail-count low + max-attempts=1, then make the
      target unreachable (block ICMP to it, or point AutoPing at lafayette and `iptables -A
      INPUT -p icmp -j DROP` on lafayette briefly) and confirm the EPCR2 cycles the outlet.
      Restore sane settings + the firewall rule afterward.
- [ ] **End-to-end** (optional, controlled): once confident, let a real lockout occur (or
      force one) and confirm unattended recovery in ~10–15 min instead of hours.

## 6. Long-term — PiKVM UI element
- [ ] Add a power button/menu item in PiKVM for one-click status/cycle. Options: a small
      custom web page or a `kvmd` user-script wrapping `epcr2-power`. Lower priority than
      getting AutoPing + the CLI working. Revisit after the hardware root cause is resolved.

## Notes
- This recovery works **regardless of root cause** (PSU/board/BMC) because it cuts AC
  externally — it does not depend on lafayette or its BMC being alive. It is the
  highest-leverage reliability fix while the underlying hardware fault is still unconfirmed.
- It does **not** fix the cause; keep `log-thermals` running and pursue the on-site PSU /
  multimeter / memtest work in `docs/hang-onsite-fix-plan-2026-06-15.md`.
