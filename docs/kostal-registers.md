# KOSTAL Modbus register notes (not a universal interface)

The guard targets the documented KOSTAL PLENTICORE Modbus TCP battery-control interface. A different manufacturer's Modbus address is NOT interchangeable.

| Decimal register | Access in guard | Documented purpose |
| --- | --- | --- |
| 5 | Read | Modbus byte order for floating-point data |
| 1040 | **Write/read** | Maximum battery discharge power limit, absolute, in watts (Float, 2 registers) |
| 1042 | Read | Minimum battery state of charge, percent (Float) |
| 1078 | Read | Maximum discharge power as reported by the battery/BMS (Float) |

The G3-only battery limitation family 1280/1282/1284/1286/1288 has a **different cyclic-write/fallback design** and is NOT controlled by this application. Do not mix register families.

Manufacturer primary source: KOSTAL MODBUS TCP & SunSpec Interface Description, revision 2.9, 17 July 2026, sections 3.4 and 3.5, available through KOSTAL's downloads. [KOSTAL G3 external battery control](https://documents.kostal.com/PLENTICORE-G3/BA/de-DE/66838283518756363.html).

Written KOSTAL support confirmation (30 October 2026, case retained privately by project maintainer): register 1040 does **not** need periodic refresh and even writing at one-second intervals has no impact on the device's storage. This confirms the manufacturer position on storage wear for this register, not a particular firmware or writeback strategy.

**Control return:** The official inverter instructions state that after external control signals cease for the configured timeout, internal battery control resumes. This is distinct from whether register 1040's readable contents reset immediately. Confirm actual device behavior before commissioning.

Common default TCP port 1502 and Unit ID 71 are not a promise that they match every inverter.
