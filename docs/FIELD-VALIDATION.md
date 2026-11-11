# Field validation: unified guard v0.8.0-beta with fast-charge pre-arm hotfix

**Status (11 November 2026):** Classic fast-charge protection and release were observed on one live KOSTAL PLENTICORE G3 installation. This is a **single-site field test**, not a certification, universal compatibility result or verification of the optional intelligent planned-charge budget.

Only aggregated, anonymized measurements are included here. Raw logs, exact local identifiers, private source paths, real configurations and detailed energy/SoC time series remain private.

## Why the hotfix was needed

**Observed before the fix:** During a brief EVCC-initiated fast-charge test, the vehicle reached approximately 9.7 kW while the home battery supplied approximately 7 kW. No register-1040 guard write was recorded during that short high-load interval. The former check required both EVCC charging=true and chargePower >=500 W.

**Evidence-based diagnosis:** EVCC initially reported low ramp-up power; a large-power value appeared shortly before the session was stopped for safety. At a 15-second guard poll interval the old gate could **miss the matching snapshot**. The precise missed polling instant is not directly proven; this is a code- and log-supported timing explanation, not proof that KOSTAL Modbus writing failed.

## Tested correction

1. **Pre-arm:** Explicit EVCC mode=now with connected=true requests *classic* KOSTAL protection even if charging is not yet active and EVCC power is still 0 W. This does not start the vehicle, change EVCC modes or grant additional intelligent battery budget.
2. **Retain while stopping:** Once classical protection is active, changing the EVCC mode from now to smart/off does not release register 1040 while an attached vehicle is still charging at/above the configured threshold. Unrelated ordinary PV Smart charging cannot initiate a new protection session solely from this retention rule.
3. **Release:** Once actual charging stops, the guard stops sending 1040 commands. The inverter's internal-control return depends on its configured external-control timeout.

Implementation: battery_control_guard/protection.py. Synthetic Modbus loopback regression: tests/test_end_to_end_loop.py.

## Real charging session after the hotfix

| Check | Observed evidence | Assessment |
| --- | --- | --- |
| Protection before high power | EVCC requested the charge; the guard wrote verified 1040=0 W *before* EVCC reported ~9.8 kW vehicle power. | **Passed** |
| Active dynamic KOSTAL limit | Over about two hours of charging, 1040 was adjusted dynamically; example readback about **320 W**, with comparable low battery discharge. | **Passed** |
| Charge authority | No autonomous EVCC charge start/stop by the guard; user-controlled stop at the end. | **Passed for observed case** |
| Controlled relinquishment | After actual charging stopped, the guard announced release and logged **no further 1040 writes** within the observation window. | **Passed** |
| Normal-regulation indication | Later 1040 readbacks rose to approximately **7.1 kW** instead of a few hundred watts. | **Observed; consistent with inverter recovery** |
| Positive intelligent plan budget | Not yet separately tested in a real eligible planned-charge session with the integrated beta. | **Still unverified under load** |

The higher register value does **not by itself identify** the exact internal failback mechanism or uniquely rule out an external actor changing it. Register contents and true physical control state are different observations.

## Scope and uncertainty

- One G3, one EVCC-controlled vehicle/charger and one home battery setup were observed.
- Initial 0 W pre-arm temporarily prevents battery discharge; normal dynamic house-use allowance follows the vehicle ramp.
- This one session does not establish other inverter firmware, G2, MDC or multi-inverter support.
- No complete black-out, general third-party rollback or positive intelligent budget under an eligible v0.8.0 planned charge has been demonstrated.
- The user-selected *intelligent* total SoC reserve does **not** automatically change KOSTAL's physical minimum SoC. Classic protection can still allow household battery use down to the inverter's own minimum.
- The early failure and corrected success are two different sessions. The exact mechanism of the initial missed control sample is plausible, not conclusively measured.

Raw timestamps, device identifiers, personal departure plans, private logs and household usage history are deliberately omitted.
