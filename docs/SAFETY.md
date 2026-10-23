# SAFETY: experimental inverter control

This controller issues **live Modbus commands** that change battery discharge behavior. No warranty. Read vendor documentation and ensure the installation is operated by qualified persons where applicable.

## Preconditions before ARMING

- Verify your exact KOSTAL inverter firmware and external battery-control availability.
- Verify the KOSTAL external-control **timeout / failback** on your hardware.
- Confirm EVCC power sign conventions, freshness and coherence, loadpoint modes and single-battery-object shape.
- Ensure EVCC and all other software **cannot compete** for the same battery control; particularly register 1040.
- Back up your EVCC/inverter configuration, establish a rollback procedure and test physical recovery.
- Restrict Modbus/TCP to the trusted LAN; never expose the interface to the Internet.

## Inert-by-default

- ARMED=false; example host 192.0.2.10 (reserved documentation subnet).
- install.py refuses to overwrite an existing installation and never starts a service.
- check.py only performs read operations via the controller's --check mode.
- No production config, secrets, telemetry logs, backups, or serial numbers should be committed.

## Limitations / failure modes

- **No circuit isolation:** the cap is global. This is not proof that the EV receives no battery energy.
- **Metering:** stale but internally consistent readings may still produce a wrong limit.
- **Network loss:** the software cannot enforce 0 W if Modbus is unreachable; failback depends on KOSTAL timeout and device settings.
- **Stopping:** the controller deliberately stops refreshing 1040 rather than restoring a stale high setting; recovery is timeout-based, not immediate.
- **EVCC changes:** upgrades can change REST state fields and classification of charging modes.
- **Min SoC:** the guard reads register 1042, but the inverter and BMS remain responsible for electrical safety.
- **Unverified other hardware:** neither another manufacturer nor another KOSTAL firmware generation is automatically supported.

The supplied unit tests are offline software tests, **not** inverter hardware integration tests or a hard-power-loss verification.

## Control refresh and non-volatile memory

The example configuration refreshes register 1040 every 30 seconds during active control (or sooner if the target changes). Verify that this is safely shorter than the actual inverter external-control timeout, allowing for delays and network failures. The 60-second timeout used on the original tested system is **not** a universal device guarantee.

Do **not** assume that Modbus register 1040 writes are guaranteed to be RAM-only or guaranteed free from non-volatile storage wear. Explicit manufacturer confirmation about internal write handling was not available for this release.
