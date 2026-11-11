# Safety, failure modes and test evidence — v0.8.0-beta

**Experimental software. It writes to an energy-storage inverter.** It is not a hardware interlock, certified battery management system, grid-compliance device or substitute for qualified electrical work.

## Physical and control limitations

- KOSTAL register 1040 limits **total maximum discharge power**, not a physically segregated battery-to-house power path. The EV may still indirectly use battery energy during transients.
- The calculation uses EVCC's measured home/PV/grid/EV/battery power. Incorrect meter locations, delayed snapshots, negative signs or unavailable data can produce incorrect instructions.
- Vehicle charge start/stop belongs to EVCC or the authorized charger. Intelligent mode only provides storage permission for an already eligible charge, NEVER starts the EV.
- BMS, KOSTAL minimum SoC and inverter operating mode remain relevant. Software SoC reserve is a control policy, not a guaranteed battery shutdown point.
- A faulty forecast can result in unexpected grid imports or an inaccurate planned reserve. Additional intelligent energy is refused when valid current forecast/permission is unavailable.
- Power failure, Modbus outage, OS stall or unrelated third-party battery controllers can compromise the intended behavior. An OS instance lock applies only to the same state directory.
- **Automatic evcc Optimizer battery control (battery/full) is not compatible with simultaneous 1040 control by this Guard.** Turn off automatic optimizer battery control and verify the absence of other Modbus writers. The guard does not detect every third-party/optimizer transition.
- If 1040 stops receiving commands, control return depends on the device's **configured external-control timeout**. Do not infer from a readback that control mode is already released.
- Other inverter manufacturers, G3 MDC multi-battery setups, and externally commanded Octopus/Zappi charges are not validated for this beta.

## KOSTAL register specifics

The writer uses KOSTAL **1040** (max discharge power, Float/W); it reads **1042** (min SoC), **1078** (BMS max discharge) and **5** (byte order). It does not write the distinct G3 register family 1280–1288. KOSTAL revision 2.9 (17 July 2026) documents these as separate mechanisms.

A manufacturer support answer received 30 October 2026 stated 1040 need not be cyclically written and even rapid repeated writes have no effect on device memory. This addresses the originally raised flash-wear concern for register 1040; it does not certify all aspects of our firmware logic.

## Evidence (clearly separated, as of 11 November 2026)

**Observed before the hotfix:** During a short ~9.7 kW fast-charge attempt, the battery supplied approximately 7 kW and no protective register-1040 write was recorded. The previous 500 W eligibility gate could miss the charging ramp between polls; the exact failed sampling instant was not proven.

**Hotfix tested:** Explicit EVCC fast mode with a connected vehicle now pre-arms classic 1040 protection at 0 W even before EVCC reports charging. Existing protection continues while the attached car physically keeps charging after an EVCC mode transition. Three new offline tests cover these cases.

**Observed after the hotfix:** The corrected unified v0.8.0-beta on one KOSTAL G3 wrote verified register 1040=0 W before high EV load, regulated at a few hundred watts during ~9.8 kW charging, released after the genuine charging stop, issued no later guard 1040 writes in the observation window, and showed later higher register readback consistent with return to ordinary regulation.

**Software-tested:** Internal development 105/105 after hotfix; public portable release candidate 110 discovered, 107 passed, 3 intentionally skipped optional private legacy-source parity checks. Historical shadow comparison over 13,000 points covered *selected classic protection states*, not all possible cases.

**Not established:** Real positive intelligent plan-budget release with combined v0.8.0-beta; device-agnostic external timeout/reset cause; physical total power-loss behavior; independent third-party rollback; all firmware/battery combinations; guaranteed savings or battery wear effects.

**Reserve semantics:** A higher user-configured total SoC reserve protects the intelligent *extra EV energy permission* but does not automatically replace KOSTAL's physical minimum SoC during classic household protection. Verify the inverter's actual minimum separately.

See [Anonymized field validation](FIELD-VALIDATION.md) and [Implementation changes](IMPLEMENTATION-CHANGES.md).

## Before approval to activate

Require: (1) verified exact hardware/firmware; (2) correct Modbus registers and inverter management mode; (3) EVCC power balance and state ownership; (4) baseline/maximum power limits; (5) correct and retained night budget; (6) absence of all competing controllers; (7) failback and recovery procedure; (8) independent checks of intelligent vehicle/plan matching.

Keep Modbus on trusted LAN. Do not forward ports. Do not post actual config or tokens publicly.

Primary sources:
- [KOSTAL external battery management](https://documents.kostal.com/PLENTICORE-G3/BA/de-DE/66838283518756363.html)
- [KOSTAL battery settings](https://documents.kostal.com/PLENTICORE-G3/BA-DE/de-DE/473255435778655115.html)
- [EVCC battery features](https://docs.evcc.io/de/features/battery/)
- [EVCC charge plans](https://docs.evcc.io/de/features/plans/)
