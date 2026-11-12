# Home Assistant dashboard — Battery Control Guard

The dashboard is an **optional frontend of this same GitHub project**, not a separate controller. It uses the local read-only status exporter already included in v0.8.0-beta. The original local Lovelace Guard view was extracted without publishing the complete household charging dashboard, its other integrations, historical energy data or local configuration.

## What it does (and what it does not)

- Shows live status, effective KOSTAL 1040 display values (if mapped to HA sensors), estimated battery/SoC recovery, model-based extra-budget preview, actual controller permission and reasons.
- Shows historical home-battery SoC and real KOSTAL minimum SoC using **existing HA Recorder data** when mapped.
- Can write **only** a deliberately configured `input_number` safety-reserve helper through the normal Home Assistant UI service. The core Guard must separately be configured to **read that exact helper** in its private TOML settings for this to affect intelligent permission. Without the helper the slider is disabled.
- The Classic / Intelligent controls **switch views only**. They do not switch the backend's operating mode, start charging, stop charging, change KOSTAL 1040, alter EVCC or bypass reserve checks.
- The frontend does not directly connect to EVCC, MQTT, the inverter or a vehicle.

**What is verified:** Browser tests cover displayed status, stale-status rejection, view switching, valid helper writes and disabled controls without a helper. The original live household dashboard remains untouched. This extracted standalone package has not yet been tested in an independent third-party HA installation.

## Installation (same repository)

Prerequisites: Home Assistant with a writable local `config/www` directory, a supported v0.8.0-beta guard on the same Linux host as the optional exporter, and a normal user account that can read the Guard's deliberately published `/run/battery-control-guard` JSON reports. HA installed on another machine requires a separate reviewed transfer solution; don't copy credentials or assume the local paths will work remotely.

From a **current main branch checkout** of this repository:

```sh
sh scripts/install_ha_ui.sh --ha-config /absolute/path/to/homeassistant/config --dry-run
sh scripts/install_ha_ui.sh --ha-config /absolute/path/to/homeassistant/config
```

The optional installer copies the dashboard into `config/www/guard/battery-control-guard-card.js` and stages a **disabled** per-user export timer. It will not start/stop the Guard, alter HA dashboards/config, change the backend mode or issue any inverter commands. Existing differing files are preserved unless `--replace` is explicitly requested.

In Home Assistant, add a **JavaScript module** resource:

```text
/local/guard/battery-control-guard-card.js
```

Then add a Manual Lovelace card:

```yaml
type: custom:battery-control-guard-card
urls:
  status: /local/guard/guard-v070-status.json
  forecast: /local/guard/guard-recovery-v072.json
entities:
  battery_soc: sensor.example_home_battery_soc
  kostal_min_soc: sensor.example_kostal_min_soc
  discharge_limit: sensor.example_kostal_1040_limit
  guard_status: sensor.example_guard_status
  guard_requested: binary_sensor.example_guard_requested
  reserve: input_number.example_battery_guard_reserve
  forecast_ready: binary_sensor.example_guard_service
  weather: weather.example_local_weather
  history_soc: sensor.example_home_battery_soc
  history_min_soc: sensor.example_kostal_min_soc
```

These entity names are **illustrative placeholders**, not names provided by this repository. Replace each one with a sensor/helper that actually exists on your own HA system, and **remove unused mappings**. No physical KOSTAL minimum-SoC write is provided by this frontend.

## Enable the optional status exporter

The Guard's core status/forecast bridge remains separate from the visual card to retain the existing one-service, one-Modbus-writer architecture. Verify that the core service is running and that the two permitted source files exist under `/run/battery-control-guard`.

To activate the **separate read-only exporter timer** after installation:

```sh
systemctl --user daemon-reload
systemctl --user enable --now battery-control-guard-ha-export.timer
systemctl --user status battery-control-guard-ha-export.timer
journalctl --user -u battery-control-guard-ha-export.service -n 30 --no-pager
```

The optional exporter copies valid, fresh data to two **legacy-compatible** paths under `www/guard`: `guard-v070-status.json` and `guard-recovery-v072.json`. Their schema/version/time checks are performed by the exporter and repeated by the UI. There is no second EVCC/KOSTAL Modbus writer. A stopped service, missing intelligent export or expired data is **not reported as a valid permission**.

For a single, non-recurring export without a timer:

```sh
BCG_HA_PUBLIC_DIR=/absolute/path/to/homeassistant/config/www/guard \
  python3 scripts/ha_status_export.py
```

This exporter requires a reachable local Home Assistant web folder. The generic core `install.sh --install` does not set up Home Assistant or start the optional timer. If the Guard and HA are on different hosts, the bundled on-host exporter will not work without additional installation-specific wiring.

## Optional reserve helper

Create a Home Assistant **Number helper** with a reasonable range compatible with the frontend (8–30 percent, step 1). Then assign its **actual** `input_number` entity ID under `entities.reserve` in the card. The core TOML setting `home_assistant.reserve_entity` must be set to the **same** entity and its HA authentication material stored privately according to [CONFIGURATION.md](CONFIGURATION.md).

The frontend cannot force the Guard to adopt a changed reserve. A successful `input_number.set_value` service response confirms only submission to HA; the next valid Guard status must be checked before asserting that its decision reflects the new value.

## Privacy and safety

The files under `/local/guard` are static web files from HA's `www` directory. Depending on HA/proxy configuration, they can be accessible to other clients. **Never copy raw logs, secret tokens, full EVCC state, personal energy history, VINs or unfiltered runtime state into www.** The exporter allows only approved status fields and observation-mode forecast data.

Avoid exposing HA to the public internet without proper authentication and access controls. Do not run multiple KOSTAL Modbus controllers, and keep EVCC automatic optimizer battery control off as explained in [SAFETY.md](SAFETY.md). An HTTP-successful JSON fetch or a UI indicator alone is not evidence of a physical inverter mode transition.

## Troubleshooting

- **All live values —:** Replace example entity IDs with real HA entities. Inspect browser dev tools and the status JSON path.
- **Intelligent status unknown:** Check export timer, `battery-control-guard.service`, schema version and freshness; classic guard operation can still be present.
- **Slider disabled:** Missing/unavailable/wrong-type `input_number` entity. Do not interpret a slider movement as a successful backend configuration.
- **Chart missing:** Set two HA Recorder-backed sensors, and ensure the history graph is supported by your HA version.
- **No forecast:** The Guard may be running in protection-only mode or the intelligent observation report may be stale/missing.
- **Service runs but browser still sees old content:** Refresh HA browser cache after registering the resource.