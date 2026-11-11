# v0.8.0-beta — proposed GitHub pre-release notes

**Status: ready for maintainer review. No public push/tag or GitHub Release has been made.**

## Highlights

- **One application, one systemd service, one KOSTAL Modbus writer.** Replaces the old public single-file guard and two separate later local programs.
- Dynamic household-aware KOSTAL register-1040 battery discharge power cap during supported EVCC charging.
- Optional PV/household forecast budget for already active qualifying EVCC charging, with total reserve, vehicle/plan matching and spent-night tracking.
- **EVCC remains the only authority for vehicle charging.** The Guard neither starts nor stops an EV charging session.
- **Fast-charge pre-arm hotfix:** Explicit fast mode with a connected vehicle activates classic KOSTAL protection *before* EVCC reports the AC power ramp. Once protection starts, mode changes do not remove it while the attached EV is still actively charging.
- Public installation is disarmed by default. Existing v0.4.0 users need a controlled migration; the older version remains in Git history.

## Why the hotfix matters

In a brief pre-hotfix test, an EV charger reached around 9.7 kW with around 7 kW home-battery discharge, while no 1040 guard write was observed. Old eligibility needed charging=true and chargePower >=500 W; the suspected sampling window was too short. The specific missed poll was not conclusively reconstructed.

A later live retest with the corrected code observed:

- 1040 **0 W** command/readback before ~9.8 kW EV charging power was first reported.
- Continuous dynamic 1040 control, at times around **320 W**, during a roughly two-hour charge.
- Logged release at actual charge end, no further guard 1040 writes in the observation window, and later KOSTAL register values returning near 7.1 kW.

**Conclusion:** Classic fast-charge protection and logged release were field-tested successfully on **one KOSTAL G3 setup**. The higher readback is consistent with inverter takeover but does not, by itself, identify the exact internal reset cause. The separate optional *positive intelligent plan budget* remains without a physical unified-beta test.

## Tests and privacy

- Full internal beta development suite after the hotfix: **105/105** passed.
- Public clean checkout: **110 discovered; 107 passed; 3 intentionally skipped** optional legacy-parity tests requiring an unpublished independent old source.
- Earlier 13,000+ shadow points: no differences in the *subset of classic states compared*; this does not verify every stateful behavior.
- Public evidence is aggregated/anonymized. Raw EVCC/HA/KOSTAL logs, household consumption history, secret files, identifiers, original state ledgers and personal configs are **not included**.
- Physical power-loss failback, other inverter/firmware models, multi-loadpoint intelligent mode and external Octopus/Zappi charging detection are not verified.

## Breaking changes / migration

Python 3.11+ and TOML; new service battery-control-guard.service, package battery_control_guard, separate private state directory and mandatory safe migration marker in intelligent mode. Do **not** keep the old evcc-battery-guard.service running. Do not use the private site-specific deployment scripts as a universal installer.

Read [Migration](MIGRATION.md), [Installation](INSTALLATION.md), [Safety](SAFETY.md), [Change detail](IMPLEMENTATION-CHANGES.md) and [Field validation](FIELD-VALIDATION.md) before activation.

**Conflict warning:** Do not simultaneously enable evcc automatic Optimizer battery control (battery/full) or another Modbus writer to the KOSTAL battery registers. This is a required operator setting, not proof that the current guard can detect every competing controller.

## Feedback

Reports should contain only anonymized inverter generation/firmware, EVCC version, observed register transitions and safe fault/release behavior. Never post credentials, VINs, device serials, personal schedules, private IPs or full logs.
