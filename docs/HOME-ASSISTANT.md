# Optional Home Assistant status export

The optional standalone Lovelace card is in this same repository (post-tag). See [UI installation](UI-INSTALLATION.md). The original v0.8.0-beta release archive predates this addition.


Home Assistant is **not required** for the ordinary protection mode. Intelligent mode can use the fixed SoC reserve without Home Assistant, or can use a deliberately configured HA reserve entity and a private token file.

## Optional reserve read

Configure home_assistant.api_url, home_assistant.token_file and home_assistant.reserve_entity in your local TOML. The token file contains a full Bearer authorization header and must be accessible to the dedicated bcguard service account, which runs with ProtectHome=yes. Use a private directory outside user homes. If an HA entity is configured but cannot be read reliably, the intelligent extra battery allowance must be withheld.

## Read-only status/forecast bridge

The core application may publish only status-intelligent.json and forecast.json under /run/battery-control-guard. The separate example script scripts/ha_status_export.py checks service status, data version, schema, timestamp and allowed fields before copying two JSON files into a chosen *local* Home Assistant web directory.

Set the destination explicitly through the environment variable BCG_HA_PUBLIC_DIR. It defaults to a nonexistent path to avoid accidental publishing on a new machine.

~~~bash
BCG_HA_PUBLIC_DIR=/your/homeassistant/config/www/guard \
  python3 scripts/ha_status_export.py
~~~

The script writes historic compatibility filenames guard-v070-status.json and guard-recovery-v072.json. These filenames match one older custom dashboard; **they are not a general Home Assistant integration API** and are not appropriate for every installation.

The provided generic installer does not configure a Home Assistant account, dashboard resource, bridge timer or web server; those must be configured intentionally for the deployment. Do not copy or publish private HA YAML/token files from another installation.

The script is read-only as regards EVCC and KOSTAL. Publishing operational energy data to an HA web folder means those JSON files may be accessible to clients permitted to access that web path. Do not expose the installation publicly without adequate access control.
