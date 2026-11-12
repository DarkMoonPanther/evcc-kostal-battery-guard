# EVCC KOSTAL Battery Control Guard

**v0.8.0-beta — experimental, third-party community project; not affiliated with EVCC or KOSTAL.**

One configurable Python application combines dynamic house-battery discharge protection and **optional** forecast-based battery budgeting while EVCC controls an electric vehicle. This package replaces the former v0.4.0 single-file architecture; that version remains accessible through the Git history and v0.4.0 tag.

> **Beta / field evidence (11 November 2026):** The **fast-charge pre-arm hotfix** has now passed a real KOSTAL G3 charge session: register 1040 was capped at 0 W **before** EVCC first reported ~9.8 kW EV power, then dynamically limited during charging; the guard ceased writes at charge end, and later readback rose toward normal values. This is **one-site evidence of classic protection and logged release**, not proof of universal inverter behavior. The optional *intelligent positive EV battery budget* remains unvalidated under real eligible plan charging in the integrated beta. Local tests: **110 discovered, 107 passed, 3 optional historic comparisons skipped**. Live hardware Modbus writes are possible.

## Design principles

- **EVCC alone decides if/when the EV charges.** Battery Control Guard does not start or stop vehicle charging.
- **Protection mode:** dynamically caps total KOSTAL battery discharge during supported fast, scheduled, Smart-minimum and preconditioning situations while leaving capacity for ordinary house load.
- **Fast-charge pre-arm:** EVCC explicit fast mode with an attached vehicle already triggers classic protection before the high-power ramp; an existing cap survives a delayed charging stop even if EVCC changes mode. See [hotfix and field test](docs/FIELD-VALIDATION.md).
- **Intelligent mode (opt-in):** permits additional, bounded home-battery energy for certain already-active eligible EVCC charges, using PV recovery and consumption forecasts, effective SoC reserve, vehicle/plan identity and a spent-night-budget ledger.
- The application runs as **one systemd service**, with internal modules and **one Modbus writer** controlling KOSTAL register 1040. It does **not** physically isolate the EV from household wiring.
- A process lock prevents two instances that use the *same* state directory; it does not exclude unrelated software or another state directory. The operator must ensure sole control of the inverter battery registers.

## Compared with the evcc Optimizer

The **[evcc Optimizer](https://docs.evcc.io/en/features/optimizer/)** plans energy use across PV, home batteries, electricity tariffs and eligible EV charging. Depending on its settings, it can recommend or automatically apply battery and charging decisions.

**Battery Control Guard solves a narrower KOSTAL-specific problem:** during eligible EVCC-controlled charging it sets a **dynamic discharge-power limit in watts** via Modbus register **1040**, so the home battery can still cover household demand instead of being fully blocked. Its optional forecast module grants a limited additional EV energy budget when the predicted reserve allows it. **It never starts/stops EV charging and does not replace tariff-based whole-home optimization.**

**Do not operate both as battery controllers:** evcc Optimizer automatic battery modes (`battery`/`full`) can compete for the same KOSTAL control registers. Use evcc automatic Optimizer control `off` with this Guard and ensure no other active battery-control writer. This is a configuration requirement, not an assertion that the Guard already detects every optimizer conflict.

Reference: [evcc 0.318.2 KOSTAL battery-mode implementation](https://github.com/evcc-io/evcc/blob/0.318.2/templates/definition/meter/kostal-plenticore-gen2.yaml).

## Requirements / verified coverage

| Requirement | Facts |
| --- | --- |
| Python | **3.11+** (standard library; tomllib) |
| OS | Linux with systemd for the packaged service / installer |
| EVCC | Reachable /api/state with coherent house, grid, PV, EV and one battery; locally tested with **EVCC 0.318.2** |
| Inverter | KOSTAL PLENTICORE with manufacturer-documented **external battery control over Modbus TCP**, enabled by a qualified installer; beta startup observed on **one G3** |
| Modbus | Common default TCP 1502, Unit 71 — check your individual inverter |
| Intelligent mode | One EVCC loadpoint (index 1) and explicitly configured exact vehicleName, usable PV/household history, valid reserve and session identity |
| Home Assistant | Optional; only needed when using an HA reserve entity or the example HA status exporter |

**Not validated:** the integrated beta on PLENTICORE G2, other G3 firmware combinations, MDC setups, other inverter brands, multiple loadpoints, or Octopus/Zappi external-charge recognition. Older G2 community feedback refers to earlier guard versions.

## Local read-only preview — no inverter writes

~~~bash
python3 --version
cp config.example.toml config.toml
# Edit only the copied file. Make application.state_dir a writable absolute path.
# Keep application.execution="observe" and application.armed=false.
python3 -m battery_control_guard.app --config config.toml --check-config
python3 -m battery_control_guard.app --config config.toml --observe
python3 -m unittest discover -s tests -v
sh install.sh --dry-run
~~~

Observe reads EVCC state and writes only a local status report. It does **not** open a KOSTAL Modbus connection or issue EVCC POST commands. The example config is intentionally **disarmed**.

For a brand-new installation, read [Installation](docs/INSTALLATION.md). The installer only places disarmed files and a systemd service; it does not start or enable control.

For existing v0.4.0 deployments, follow [Migration](docs/MIGRATION.md), not the old installer. For previous private 0.6/0.7 controllers, preserve and migrate spent night budgets. **Never run old and new battery controllers simultaneously.**

## Safety-critical technical scope

Register **1040** is the KOSTAL-specific maximum discharge power limit (W, Float). The app additionally reads **1042** (minimum SoC), **1078** (BMS max discharge) and **5** (byte order). It does **not** control the G3 1280–1288 battery limitation family. See [Register reference](docs/kostal-registers.md) and [Safety](docs/SAFETY.md).

On release of active protection the guard stops 1040 write commands, relying on the configured KOSTAL external-control timeout to return to normal battery regulation. This must be tested on the specific device; the readable register value and actual control mode are different observations. In an October 2026 manufacturer-support response, KOSTAL stated that even frequent writes to register 1040 do not cause storage wear.

Forecasts and HA reserve inputs are software policy, not hardware protection guarantees. If forecasts/HA data required by a configured intelligent mode become unusable, the guard must refuse *extra* EV energy permission. Misconfiguration, network loss or failure can still lead to grid energy use or other unintended outcomes; see limitations.

## Optional integrated Home Assistant dashboard (added 12 November 2026)

The existing project now contains an optional, standalone Lovelace card based on the original local Battery Guard view. It displays classic protection, intelligent permission and forecast budget, recovery, HA history and diagnostic reasons. A configured Home Assistant input_number helper can change the intelligent SoC reserve. **Classic / Intelligent is only a view selector; it does not change the running Guard mode.**

Read [UI installation](docs/UI-INSTALLATION.md). The optional installer stages a disabled HA export timer, and the frontend never makes KOSTAL Modbus or EVCC charge-control requests.

The immutable original `v0.8.0-beta` tag from 11 November does **not** include this newer frontend. It is integrated into current source, not a separate repository or a replacement for the original release archive.

## Monitoring

~~~bash
systemctl status battery-control-guard.service
sudo journalctl -u battery-control-guard.service -n 80 --no-pager
sudo cat /var/lib/battery-control-guard/status.json
~~~

Do not post private EVCC/KOSTAL logs, token files, state/budget ledger or real config to GitHub issues.

## Documentation

- [Deutsch: Kurzanleitung](docs/KURZANLEITUNG-DE.md) · [Install](docs/INSTALLATION.md) · [Configuration](docs/CONFIGURATION.md) · [Migration](docs/MIGRATION.md) · [Rollback](docs/ROLLBACK.md)
- [Safety](docs/SAFETY.md) · [Compatibility](docs/COMPATIBILITY.md) · [Architecture](docs/ARCHITECTURE.md)
- [Optional Home Assistant export](docs/HOME-ASSISTANT.md) · [Beta release notes](docs/RELEASE-NOTES-v0.8.0-beta.md) · [Changelog](CHANGELOG.md)
- [Anonymized field validation](docs/FIELD-VALIDATION.md) · [Detailed implementation changes](docs/IMPLEMENTATION-CHANGES.md)
- [Security reporting](SECURITY.md)

Development included ChatGPT assistance; source and documentation require independent technical review. [MIT License](LICENSE).
