# evcc-battery-guard

**Experimental third-party extension for EVCC and KOSTAL PLENTICORE.** Not affiliated with EVCC or KOSTAL.

During EV fast, planned, minimum-SoC recovery, or cost-optimized charging, this tool dynamically limits the home battery's *total maximum discharge power*, aiming to leave battery energy available to ordinary household load. This does **not** physically isolate EV and home circuits.

Based on the locally deployed Mokka Battery Guard **v0.4.0**. Production use on a single installation does not establish general hardware compatibility.

## Compatibility

- EVCC with accessible REST state fields for house, grid, PV, loadpoints and one battery object containing SoC.
- **KOSTAL PLENTICORE** with the documented Modbus battery-control interface; verified only on one G3 deployment, not across all G3 firmware versions.
- Linux with systemd, Python 3.10+ (standard library only), and access to inverter Modbus/TCP and EVCC REST.
- **One writer only** to battery-control registers. EVCC batteryDischargeControl must be false during active guard control. Do not run another battery-write automation concurrently.

**Register 1040 is KOSTAL-specific, not a universally portable Modbus address.** See [register documentation](docs/kostal-registers.md).

## Operating principle

The guarded target is computed as:

```text
candidate = max(0, homePower - pvPower - gridMargin)
limit = min(candidate, pre-session register 1040 value, BMS maximum register 1078)
```

For example, with household load 2000 W, PV 1500 W, grid margin 100 W, the initial candidate is 400 W. The code additionally checks EVCC meter consistency, minimum battery SoC and the active charging mode. It writes only KOSTAL register 1040 (FC16) and verifies readback.

The cap applies to **all** battery discharge, not separately to the EV. Measurement delays, configuration mistakes or power transients can affect results.

## First installation (inert by default)

Read [SAFETY.md](docs/SAFETY.md) before use.

1. Review the source and run `python3 -m unittest discover -s tests -v`.
2. Run `sudo python3 install.py`. On first installation, it copies files only. It neither changes EVCC nor enables/starts the service. Existing destination files cause it to refuse installation.
3. Edit `/etc/evcc-battery-guard.conf`: replace the documentation address `192.0.2.10`, and verify unit ID, port, EVCC URL and metering. **Leave ARMED=false**.
4. Run `sudo python3 check.py`. This performs a **read-only** state and Modbus check.
5. Only after a site-specific battery-control and external-timeout verification: set EVCC batteryDischargeControl to false; explicitly set ARMED=true; then manually enable and start `evcc-battery-guard.service` with systemd.

**The fifth step enables live inverter control.** Do not treat it as part of an automated installer.

### Disable / rollback

Return EVCC's battery-control setting to the intended safe configuration and stop the guard. The guard **stops writing 1040 instead of restoring a saved baseline**; the inverter returns to internal operation only after its configured external-control timeout. Observe and verify this behavior on your system. Stopping the process does not instantly restore inverter control.

## Safety design (code behavior, not a hardware guarantee)

- ARMED=false refuses all Modbus writes.
- Only acts during eligible active charging and with coherent EVCC state.
- Caps register 1040 based on pre-session maximum and read-only BMS maximum (1078).
- Reads KOSTAL minimum SoC (1042) and uses hysteresis; never writes 1042.
- Refuses known conflicting EVCC battery modes.
- On inconsistent data during an active session, attempts a conservative 0 W limit.
- If communication is interrupted, this fallback write may be impossible; reliance on inverter external-control timeout remains essential.

Offline tests do not establish third-party hardware safety. Read [safety limitations](docs/SAFETY.md) and [security policy](SECURITY.md).

## Project status

**v0.4.0 source update (23 October 2026).** v0.4.0 is installed on one KOSTAL G3 system; the new retry and logging paths passed 12 local offline regression tests, in addition to the repository's original tests. A repeat of the original anomalous meter/Modbus event has not been observed and validated in production since deployment. No universal manufacturer or firmware support is claimed.

### What's new in v0.4.0

- During an **active protected charge**, one inconsistent EVCC state snapshot triggers exactly **one complete re-fetch after 1 second**. The new snapshot replaces the old one; ownership, battery mode and charging eligibility are checked again before a write.
- If the retry is still inconsistent or fails, the conservative pre-existing fallback remains (attempting a 0 W limit if the guard already owns an active session).
- FC03 Modbus read errors now include the attempted register address and register count for troubleshooting.
- The public example polls every 15 seconds and refreshes at 30 seconds (100 W change threshold). These are *example values*, not universal recommendations. The inverter's external timeout and actual behavior must be checked.

See [CHANGELOG.md](CHANGELOG.md).

## Primary sources

- [KOSTAL Modbus/SunSpec interface document, revision 2.9, 17 July 2026](https://www.kostal-solar-electric.com/fileadmin/downloadcenter/kse/BA/Protokollbeschreibung/BA_KOSTAL_Interface_MODBUS-TCP_SunSpec_with_Control.pdf)
- [KOSTAL G3 external battery control and timeout](https://documents.kostal.com/PLENTICORE-G3/BA-DE/de-DE/473255435778655115.html)
- [EVCC API state](https://docs.evcc.io/de/reference/state/)
- [EVCC battery discharge API](https://docs.evcc.io/integrations/rest-api/operations/setbatterydischargecontrol/)

## License

MIT — see [LICENSE](LICENSE). No EVCC or KOSTAL software is bundled.

## Development transparency

This project was developed with assistance from OpenAI's ChatGPT. The project maintainer defined the requirements, selected the intended behavior, and guided the configuration and testing on a real installation. AI assistance was used to develop and review the Python implementation, documentation, and offline tests.

The software has been operated on one KOSTAL PLENTICORE G3 installation, and selected code paths have passed automated offline tests. These results do not establish compatibility, safety, or reliability on other systems. The repository maintainer remains responsible for reviewing changes and documenting verified behavior.
