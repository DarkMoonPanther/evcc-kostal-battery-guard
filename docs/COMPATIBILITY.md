# Compatibility — evidence as of 11 November 2026

| Device / configuration | Direct evidence | Status |
| --- | --- | --- |
| **KOSTAL PLENTICORE G3, one installation** | Unified v0.8.0-beta with fast-charge pre-arm hotfix physically applied a 1040=0 W limit before ~9.8 kW EV load, dynamically updated 1040 under sustained load and stopped writes on charging end. Later readback rose to ~7.1 kW. | **Classic fast-charge protection and logged release tested on one G3** |
| Positive additional intelligent EV battery budget during EVCC plan | No separate live test in combined v0.8.0-beta; older versions were independently tested. | **Still beta / not physically validated** |
| KOSTAL PLENTICORE G2 | Community report for an older standalone guard version, not the combined beta. | **Community feedback only** |
| Other G3 firmware, inverter/battery combinations | Published register semantics do not ensure identical external-control/fallback behavior. | **Unverified** |
| KOSTAL MDC / multi-battery control | Other management mode and measurement topology. | **Not validated** |
| Other inverter manufacturers | Different register maps and control semantics. | **Not supported** |
| EVCC 0.318.2 | Used on the original tested installation with actual charging. | **Locally field-tested for classic protection** |
| Other EVCC versions | API fields and charging-mode behavior may change. | **Requires individual verification** |
| Multiple EVCC loadpoints in intelligent mode | Controller explicitly expects index 1 and one battery. | **Not supported** |
| EVCC automatic Optimizer battery control | Potential competing KOSTAL Modbus writer/mode. | **Do not run simultaneously** |
| Python below 3.11 | Standard-library tomllib unavailable. | **Not supported** |
| Home Assistant | Optional reserve read and site-specific read-only JSON bridge. | **Not required for protection** |
| Externally started Zappi/Octopus charging | General external-start detection not implemented. | **Not supported** |

This is a third-party experimental project, not a manufacturer-validated universal KOSTAL controller. Verify inverter model/firmware, BMS minimum SoC, register 1040, external timeout, EVCC power consistency, other writers and physical release behavior on each installation.

**Sources:** [Anonymized real test](FIELD-VALIDATION.md); [KOSTAL external battery control](https://documents.kostal.com/PLENTICORE-G3/BA/de-DE/66838283518756363.html); [EVCC battery management](https://docs.evcc.io/de/features/battery/).
