# Lafayette Server Hardware Upgrade Options (June 2026)

Replacing 2012 dual-Xeon E5-2620. Workload: ~40 Docker containers, Plex primary.
Measured peak: 10 streams / 5 transcodes, ~all 1080p/720p, 4K transcode ~never,
old CPU never >38%. Owns LSI HBA (needs 1x free PCIe x8-electrical slot).
RAM: ~7.4GB + 20GB tmpfs ceiling. Start 32GB, grow to 64/128GB.

## 2026 market reality: RAM is the story

AI/HBM demand has structurally squeezed DRAM. As of June 2026:
- **DDR5 32GB (2x16):** floor ~**$375**, typical $375-450. (Tom's Hardware, PC Guide, TechRadar)
- **DDR4 32GB (2x16):** ~**$180-260**, roughly **30-40% cheaper** than DDR5. (Tom's, Pangoly, Alibaba)
- No relief expected before late 2027/2028. Prices still rising ~30-50%/quarter.

Implication: RAM now often costs MORE than the CPU. The DDR4-vs-DDR5 delta
(~$150-200 at 32GB, and it COMPOUNDS at 64/128GB) is the single biggest lever
on this build. This pushes hard toward a DDR4 LGA1700 board.

## Evaluation verdicts

1. **DDR4 vs DDR5:** Buy **DDR4 LGA1700 (B760-D4)**. At 2026 prices the DDR4
   discount is large and grows with every expansion. This is a home server, not
   a gaming rig — DDR5 bandwidth is irrelevant to Docker/Plex. "DDR5 longevity"
   doesn't apply: LGA1700 is a dead-end socket either way, so pay less now.
2. **CPU tier:** Intel **12th/13th gen Core (LGA1700)** is the sweet spot.
   i5-13500 / i5-14500 (14C/20T, UHD 770) are the community "GOAT" for Plex.
   N100 = too few cores for 40 containers (confirmed). N305/N355 (8 E-cores)
   is viable-but-tight and has no expansion path. Core Ultra/LGA1851 forces
   pricey DDR5 + Arrow Lake Plex Linux transcode only stabilized in a **May 2026
   beta** — too new for a "runs for years" box.
3. **AMD AM5:** Skip for this workload. Radeon iGPU transcoding is real but
   weaker/less efficient than Quick Sync (~25-40% more power transcoding), and
   AM5 forces expensive DDR5. Intel Quick Sync is the whole point here.
4. **ECC (W680):** Skip. Commercial W680 boards are ~$500+ and force DDR5 ECC
   (even pricier). Not justified for a media server with no ZFS-checksum-critical
   data (you have SnapRAID parity). Spend the savings on a UPS/backups instead.

---

## Shared component: PSU (applies to all options below)

**Decided: be quiet! Straight Power 12 850W 80+ Platinum (BN515)** — already owned, $0 added.
The 14-drive array (not the CPU) drives PSU sizing, and the hang investigation
(`hang-onsite-fix-plan-2026-06-15.md`) points at **power sag under peak drive load** as the
likely freeze cause, so this is reliability-critical. Budget: ~250W steady, ~460–480W spin-up
surge (~28–35A on +12V). The 850W Platinum unit (~70A single +12V rail) covers this with
huge margin; over-spec but fine — Platinum low-load efficiency penalty is ~1–3%, and it's
already owned. Verify enough SATA power leads for 14 drives; enable staggered HBA spin-up.
Full reasoning in `hardware-sizing-2026-06.md`. (Had none been on hand: 550W min / 650W
80+ Gold recommended — the 850W exceeds both, so **add $0** to the totals below.)

## BUILD OPTIONS

### Option A — Value / Recommended ("decent breathing room")
- **CPU:** Intel Core **i5-13500** (14C/20T, UHD 770) — ~**$200-230**
  (i5-12500 ~$160-180 if you want to trim; both have UHD 770 Quick Sync)
- **Board:** **Gigabyte B760 DS3H AC DDR4** or **ASUS Prime B760-PLUS D4** — ~**$130-150**
  (B760, LGA1700, PCIe 4.0 x16 slot for the HBA, DDR4)
- **RAM:** 32GB (2x16) **DDR4-3200** — ~**$190**; expansion: 2 free DIMM slots → 64GB,
  or buy 4x16 later to reach 128GB. (Note: keep 2 slots open at start.)
- **Total:** ~**$520-570** (+ cooler/PSU/case reuse)
- **Idle:** **~15-25W** achievable (Intel 12/13th gen can hit 7-10W CPU; B760
  boards land ~15-30W system depending on tuning/NICs).
- **For:** Best price/performance. Comfortably covers 10 streams/5 transcodes
  with headroom, dodges the DDR5 tax. **This is the pick.**

### Option B — More headroom, same platform
- **CPU:** Intel Core **i5-14500** (14C/20T, UHD 770) — ~**$230-260**
- **Board:** **MSI PRO B760M-A DDR4** or ASUS Prime B760-PLUS D4 — ~**$140-150**
- **RAM:** 32GB DDR4-3200 — ~$190 (same expansion path to 128GB)
- **Total:** ~**$560-600**
- **Idle:** ~15-25W
- **For:** Slightly newer chip / marginally better clocks. Negligible real-world
  difference vs A for this workload; pick whichever is cheaper at purchase time.

### Option C — Trim-cost / lower power
- **CPU:** Intel Core **i3-12100** (4C/8T, UHD 730) ~$110 OR **i5-12400** (6C/12T,
  UHD 730) ~**$140-160**. UHD 730 still does Quick Sync 1080p/720p easily.
- **Board:** **Gigabyte B660M DS3H DDR4** / B760 DDR4 — ~**$120-140**
- **RAM:** 32GB DDR4-3200 — ~$190
- **Total:** ~**$450-490** (i5-12400) / ~$420 (i3-12100)
- **Idle:** ~**12-20W** (fewer E-cores, lower floor)
- **For:** Budget-focused & lowest idle watts. i5-12400 (6 real cores) is fine for
  40 lightweight containers + your measured Plex load; i3-12100 is the floor —
  adequate but less container headroom. Tradeoff: thinner CPU margin than A/B.

### Option D — Future-platform (only if you insist on "newest")
- **CPU:** Core **Ultra 5 235/245** (non-K, has Xe iGPU) LGA1851 — ~$250-300
- **Board:** **B860** (Gigabyte B860 DS3H, MSI B860 Gaming Plus) — ~$150-180
- **RAM:** forced **DDR5** 32GB — ~**$375+**
- **Total:** ~**$775-855** — and the 245K variant has NO iGPU (needs dGPU), so
  pick a non-K with Xe graphics carefully.
- **Idle:** ~20-30W
- **For:** Only if platform longevity matters more than ~$250 of cost. NOT
  recommended: pays the DDR5 tax AND Arrow Lake Plex Linux transcoding only
  stabilized May 2026 — immature for a years-unattended box.

---

## Bottom line
Go **Option A (i5-13500 + B760 DDR4 + 32GB DDR4)** ≈ **$520-570**, ~15-25W idle.
It nails the hard requirement (UHD 770 Quick Sync), dodges the 2026 DDR5 tax,
keeps a clean 128GB DDR4 expansion path, and leaves the HBA slot free.
If money is tight, drop to i5-12400 (Option C, ~$460). Skip AM5, W680/ECC, and
LGA1851 for this workload.

## Sources
- Tom's Hardware RAM Price Index 2026 / "32GB DDR5 now $375"
- PC Guide, TechRadar (DDR5 $375-500 floor); Pangoly/Alibaba (DDR4 $180-260)
- corelab.tech, propelrc, thegoodatheist (Plex CPU 2026: i5-13500/14500 sweet spot)
- mattgadient.com (7W idle Intel 12/13th gen)
- servethehome / dawidwrobel (W680 ECC cost & maturity)
- Unraid/propelrc (AMD iGPU vs Quick Sync efficiency)
- ServeTheHome / lowerhomeserver (N305/N355 8-core limits)
- Plex Support / vninja.net (Arrow Lake Linux transcode fixed May 2026 beta)
