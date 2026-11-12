# Detailed implementation history: v0.4.0 -> unified v0.8.0-beta

This is the community-facing implementation history. The former public **v0.4.0 tag remains preserved**. Intermediate v0.6.2 and v0.7.2 were locally developed components, not separately published stable releases.

## A. Unified architecture

| File | Change | Purpose |
| --- | --- | --- |
| `battery_control_guard/app.py` | Unified process, TOML config, explicit active/armed gate, single-instance state lock, old-service checks, protection-readiness barrier, worker lifecycle | Replace two independent programs with one application |
| `protection.py` | Retain classic KOSTAL register-1040 writer and EVCC/BMS/SoC/meter validation | One Modbus writer and house-use-oriented battery discharge cap |
| `decision.py` | Combine protection target with short-lived, plan/vehicle-specific intelligent permission | No extra EV battery budget without valid authorization |
| `intelligent.py` | Passive eligible planned/Smart-minimum grants and one-time night allocations; no EVCC charging POST | Only EVCC starts/stops car charging |
| `recovery.py`, `history.py` | PV recovery and household demand model, no extra fixed 3.3 kWh deduction | Estimate energy available until solar recovery |
| `migrate.py` | Copy prior session/budget ledger with migration manifest | Avoid repeating spent night allocations |
| `status.py`, `public.py` | Local status and strictly bounded read-only export | Operational visibility without giving HA bridge Modbus/EVCC authority |

## B. Fast-charge safety hotfix (10–11 November 2026)

**Original problem:** Before the hotfix, the core guard requested protection only when EVCC reported charging=true and chargePower >=500 W. A short actual charge attempt reached ~9.7 kW vehicle power and ~7 kW battery discharge with no 1040 guard write recorded in that short interval. A missed 15-second polling window is a log/code-supported explanation, **not a proven unique root cause**.

**Code change 1:** `protected_fast_charge()` in `protection.py` now recognizes `mode=now` plus `connected=true` before charge power rises. This pre-arms the *classic* 1040 limit and sends no EVCC command.

**Code change 2:** `Guard.run()` retains a *previously activated* classic protection session across a temporary transition from now to smart/off while the attached EV is still charging at/above the configured power threshold. This does not activate protection for a new ordinary Smart PV charging session.

**Regression tests:** Three added `test_end_to_end_loop.py` cases (connected 0 W pre-arm; disconnected vehicle no pre-arm; continued protection during delayed shutdown through mode changes).

**Live acceptance:** One later complete charge session showed a verified 1040=0 W pre-arm before ~9.8 kW vehicle load, dynamic values of a few hundred watts under sustained charging, release after actual stop and later 1040 readback near 7.1 kW. This establishes operation of classic control and logged relinquishment in this configuration, not universal KOSTAL timeout behavior. See [Field validation](FIELD-VALIDATION.md).

## C. Publication-only portability and safety adjustments

The following were applied only to the **separate publication candidate**, not silently installed on the running site:

1. Check **both** previous public `evcc-battery-guard.service` and private historical `mokka-battery-guard.service` for active/enabled conflicts (`app.py`).
2. Treat every existing migrated budget ledger as immutable, **including an allocation of 0 kWh**, to preserve SHA256 integrity (`intelligent.py`); add a regression test.
3. Use a generic `/var/lib/battery-control-guard` fallback state directory (the active TOML config remains authoritative).
4. Replace a hard-coded local Home Assistant export destination with opt-in `BCG_HA_PUBLIC_DIR`; do not distribute private deployment/rollback scripts.
5. Replace private household history fixtures with a clearly labelled synthetic formula case and opt-in private-source parity tests. The public repository does **not** contain the legacy binary/source or personal timeseries.
6. Provide disarmed first-time installer, generic config, separate migration and rollback instructions; a sample 20% total reserve is illustrative, not a recommendation or a change to the original private installation.
7. Update GitHub CI matrix for Python 3.11–3.13 and add a no-network public privacy audit.

## D. Boundaries not hidden by the release

- The optional intelligent positive plan-based extra budget has **not** yet been physically demonstrated with this combined v0.8.0-beta under load; older controller field results do not prove this.
- The EVCC Optimizer has a different whole-home cost-planning goal; this Guard implements KOSTAL-specific **watt-level battery discharge caps**, and must **not** run with EVCC automatic Optimizer battery control (`battery`/`full`) or another inverter writer.
- Manufacturer BMS, inverter minimum SoC, Modbus failure and external timeout semantics remain separate physical limitations. A higher configured *intelligent* reserve does not itself set a new physical KOSTAL minimum for classic protection.
- Public CI has three opt-in historic parity checks that will be **skipped** without a separately supplied legacy source; the remaining tests run from a clean checkout.

## Data minimization

The publication candidate excludes private EVCC/KOSTAL/HA logs, exact usage history, site-specific network IPs, authentication headers and token files, night budget/session state, device-specific identity values, local paths, backups and original evidence reports.

The test-supported fast-charge logic was taken from the verified production hotfix, with its private fallback state-directory value normalized for the public distribution. Other publication-only adjustments have offline test coverage but are not asserted to have been physically field-tested as a standalone published build.

## E. Home Assistant UI integration — post-tag, 12 November 2026

An optional, anonymized Lovelace UI derived from the existing local Guard dashboard has been integrated into the **same** repository. This extraction excludes local vehicle panels, private entity IDs, personal history reports and embedded photos. Its data comes from the existing schema-checked read-only bridge. HA entity IDs are set per installation. The Classic / Intelligent selection changes display only; the optional reserve slider calls HA `input_number.set_value` and cannot force backend mode or issue Modbus commands.

An opt-in HA UI installer copies the card and exporter and stages a disabled user timer. This has offline/browser test coverage, not independent on-site third-party validation. The original 11 November v0.8.0-beta release is unchanged.
