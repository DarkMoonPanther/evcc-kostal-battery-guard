# Changelog

## 0.4.0 — 23 October 2026

- One controlled retry of a **complete** EVCC state snapshot when the initial state is internally inconsistent during eligible charging. Wait 1 second; re-check eligibility and control ownership using only the fresh snapshot.
- Unchanged conservative fallback when both snapshots are inconsistent or the retry fails.
- FC03 Modbus read errors now identify attempted address and count.
- Public example polling/refresh intervals changed to 15/30 seconds, with 100 W change threshold; inverter external timeout must be verified independently.
- Added 12 offline v0.4.0 regression tests to supplement the earlier suite.
- No change to register map, core discharge-limit algorithm, or safe default (ARMED=false).

Validation: 12 new offline tests passed on one local development system. The guard was deployed on one KOSTAL G3 inverter. A repeat of the originally observed abnormal meter/Modbus behavior has **not** been reproduced and confirmed resolved in live charging. See [SAFETY](docs/SAFETY.md).


## 0.3.0 — public candidate (not yet released)

- Published a portable configuration template and inert-by-default installer.
- No changes to the original dynamic limit calculation.
- Default inverter IP removed from published Python source.
- Public name and systemd file paths adapted.
- Initial offline regression tests and safety guidance.

Original working system: Mokka Battery Guard 0.3.0 (single local installation).
Do not infer broad inverter firmware compatibility from that deployment.
