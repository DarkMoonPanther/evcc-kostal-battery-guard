# Security policy — EVCC KOSTAL Battery Control Guard

This experimental third-party tool may issue **live inverter Modbus commands**. It is not an independently certified protection system.

## Reporting vulnerabilities

Prefer GitHub private vulnerability reporting if enabled by the maintainer. Otherwise contact the maintainer through a private channel. Never paste inverter serials, personal email addresses, authentication headers, credentials, real configuration files, state/budget ledgers, operational logs or private IPs into public issues.

## Before enabling active mode

- Restrict KOSTAL Modbus TCP to a trusted LAN or VPN; do not expose ports to the Internet.
- Ensure a single authorized writer to the inverter battery registers. The OS lock covers **only the configured state directory**; it is not a network-wide Modbus lock.
- Confirm vendor-specific register support, byte order, charging mode, external-control fallback and BMS/SoC limits.
- Keep the configuration and any HA authorization token outside Git, owned by administrators and readable only as required by the dedicated bcguard service account.
- Use the disarmed example, offline tests, and observation mode first.
- Back up your existing installation and preserve spent-night-budget ledgers before migration.
- Never run two independent battery-control services in parallel.

See [Safety](docs/SAFETY.md), [Migration](docs/MIGRATION.md), and [Rollback](docs/ROLLBACK.md).
