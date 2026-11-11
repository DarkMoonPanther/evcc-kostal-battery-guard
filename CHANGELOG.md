# Changelog

## 0.8.0-beta — beta publication, 11 November 2026

**Breaking architecture change from public 0.4.0:** One modular Python application and systemd service replace the separate historical classic protection and intelligent forecast controller.

### Core and new functionality

- KOSTAL register-1040 watt-level dynamic battery discharge cap, EVCC coherence/ownership checks, KOSTAL min SoC 1042 and BMS power limits.
- Optional local forecast-based PV recovery, historical household demand, bounded EV battery budget and total SoC reserve (no additional fixed 3.3 kWh deduction).
- EVCC is solely responsible for vehicle charging. No automatic EVCC charging start/stop by the Guard.
- Short-lived in-process plan/vehicle permissions; historical budget ledger migration and integrity checks.
- One centralized Modbus writer, OS per-state-dir instance lock, legacy-service checks and protection-readiness barrier.
- Inert-by-default installer, TOML configuration, separated optional HA status adapter and safety documentation.

### Fast-charge pre-arm hotfix (10–11 November 2026)

- **Problem from real test:** A previous 500 W charging-power gate could miss the initial charge ramp; an early ~9.7 kW EV session briefly drew ~7 kW from the home battery while no register-1040 write was logged.
- **Fix 1:** Explicit EVCC fast mode plus connected vehicle now pre-arms the **classic** KOSTAL 1040 cap even when chargePower is still 0 W. No EVCC charge command.
- **Fix 2:** An *already active* classic protection session stays capped across now -> smart/off mode changes as long as the attached EV actually keeps charging at/above the configured threshold.
- **Verification:** Three new offline regression tests; a later real ~9.8 kW EV charge showed a verified 1040=0 W pre-arm, a dynamic limit of a few hundred watts under load, stopped guard writes after actual EVCC charging ended and later higher KOSTAL 1040 readback. Classic fast-charge protection/relinquishment confirmed **on one G3**.
- **Still beta:** The optional additional *intelligent* EV battery budget under live planned EVCC charging has not yet received its own field test in the unified version.

### Public-release-only adaptations (not installed as a production hotfix)

- Stop startup if either the former public evcc-battery-guard.service or private historical mokka-battery-guard.service remains active/enabled.
- Preserve migrated spent-night ledgers including existing zero-kWh entries; prevent changes invalidating ledger checksums.
- Normalize example state directory, anonymize fixtures and remove private archival dependencies, make optional HA status destination explicit.
- Replace site-specific scripts with public inert first-install instructions, add migration/rollback and privacy-audit instructions; leave historical public tag v0.4.0 intact.
- Public checkout tests: 110 discovered; 107 passed; 3 optional independent historic parity tests skipped (private old source intentionally not bundled). Further CI on the hosted Python 3.11–3.13 matrix remains pending until publication.

See [Detailed implementation changes](docs/IMPLEMENTATION-CHANGES.md) and [Anonymized field validation](docs/FIELD-VALIDATION.md).

## 0.4.0 — 23 October 2026

- Retry one incoherent EVCC state snapshot and revalidate eligibility and ownership before writing.
- More specific KOSTAL Modbus read error messages.
- Default example 15-second polling / 30-second active refresh / 100 W change threshold.
- Add 12 offline regressions.

## 0.3.0 — initial public commit

- Original single-file public EVCC/KOSTAL guard, inert-by-default sample, offline tests and installation documentation.

No public stable versions were released for intermediate internal v0.6.2 or v0.7.2 development.
