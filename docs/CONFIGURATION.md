# Configuration reference — v0.8.0-beta

The complete public template is [config.example.toml](../config.example.toml). Never commit a real config or Home Assistant token.

## application

- mode: protection (default) or intelligent (optional).
- timezone: real local calendar timezone for night accounting (sample Europe/Berlin).
- execution: observe or active. Requires active AND armed=true before a real --run can control an inverter.
- state_dir: absolute private directory for migration marker, session state, budget ledger, status and OS instance lock.

The lock is scoped to this state directory. Other services using their own directory may still send conflicting Modbus commands.

## evcc

- state_url: full EVCC URL ending in /api/state, for example http://127.0.0.1:7070/api/state. Validate actual household/grid/PV/battery/EV readings and charge state.
- EVCC active battery-discharge control must not compete with the guard's KOSTAL register 1040 control.

## kostal

- host: KOSTAL local LAN address (blank in sample; mandatory when active).
- port: defaults to 1502.
- unit: defaults to 71.

Verify all three parameters for the individual inverter. The 1040 register is KOSTAL-specific.

## protection

| Field | Example | Meaning |
| --- | --- | --- |
| poll_interval_s | 15 | Read/review cycle |
| refresh_interval_s | 30 | Periodic write while an active guard session requires a limit |
| min_change_w | 100 | A significant target change permits earlier write |
| grid_margin_w | 100 | Conservative house-use allowance deduction |
| min_charge_power_w | 500 | Minimum EV charge power for guarded classification |
| min_soc_hysteresis_pct | 0.5 | Minimum SoC hysteresis |
| state_coherence_w | 500 | Tolerated EVCC meter-balance error |
| readback_tolerance_w | 50 | Modbus verification tolerance |
| max_reasonable_power_w | 30000 | Sanity threshold, NOT permissible battery output |
| http_timeout_s | 3 | EVCC communication timeout |
| modbus_timeout_s | 3 | KOSTAL communication timeout |

The original G3 used a separately configured 60-second external timeout. Do not assume this applies to another inverter. Manufacturer support says 1040 need not be refreshed cyclically; refresh here supports the existing application behavior, not a universal firmware requirement.

## intelligent

- vehicle_name: exact EVCC loadpoint vehicleName (not necessarily UI nickname).
- loadpoint_id: 1 only in this beta.
- fixed_reserve_soc_pct: total SoC reserve (sample 20%), NOT an extra fixed kWh discount.

The effective minimum is the highest relevant KOSTAL/EVCC/user reserve. Intelligent permission requires a real, eligible EVCC-started charge, vehicle/plan match, fresh data, valid forecast and remaining night budget. Simply plugging in an EV or normal PV charging does not authorize additional battery energy.

## home_assistant (optional)

When reserve_entity is empty, intelligent mode uses fixed_reserve_soc_pct. If reserve_entity is provided, api_url and token_file must also be set. The token file contains the complete Bearer authorization header, requires an absolute path and must be readable to the bcguard system account; the service uses ProtectHome=yes. Store it privately outside home directories and Git, for example in a correctly permissioned /etc/battery-control-guard path. Unavailable configured HA reserve means no extra intelligent permission.

## Diagnostics

--check-config checks config shape; --observe reads EVCC without Modbus; neither proves firmware compatibility. A refused --run usually indicates disarming, legacy writer still running/enabled, a lock, invalid ledger or missing runtime prerequisites. Do not silence coherence failures by increasing tolerance without proof of correct measurements. See [Safety](SAFETY.md).
