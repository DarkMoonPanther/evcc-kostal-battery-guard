# KOSTAL-specific Modbus registers

These are **NOT universal Modbus, EVCC or SunSpec register addresses**.

| Register | Usage in guard |
| --- | --- |
| 5 | Read byte-order flag: CDAB/ABCD |
| 1040 | Maximum absolute battery discharge power in W, Float32, writable (FC16 with readback) |
| 1042 | Battery minimum SoC in %, Float32, **read only** |
| 1078 | BMS reported maximum discharge power in W, Float32, **read only** |

The implementation is designed for the documented **KOSTAL PLENTICORE** battery-control interface. Actual compatibility must be verified per device generation and firmware. KOSTAL also documents other battery control registers (e.g. 1282/1286) for certain generations; they are not used by this controller.

KOSTAL_PORT=1502 and KOSTAL_UNIT=71 originate from one deployment and must be verified for each inverter, not assumed universal.

Source: [KOSTAL Modbus TCP / SunSpec interface document, rev. 2.9, 17 July 2026](https://www.kostal-solar-electric.com/fileadmin/downloadcenter/kse/BA/Protokollbeschreibung/BA_KOSTAL_Interface_MODBUS-TCP_SunSpec_with_Control.pdf)
