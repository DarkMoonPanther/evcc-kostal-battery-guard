# Architecture — one application / one Modbus writer

The v0.8.0-beta replaces two independently launched processes with a single Python application under the systemd unit battery-control-guard.service.

## Internal components

| Module | Responsibility |
| --- | --- |
| app.py | TOML config, process startup, legacy conflict detection, OS file lock, worker lifecycle and runtime mode |
| protection.py | EVCC meter validation, core battery protection, KOSTAL Modbus TCP and **sole register 1040 write pathway** |
| intelligent.py | Passive EVCC charge eligibility, plan identity, bounded night energy allocations, user reserve and current permission |
| decision.py | In-process short-lived permission checks and effective discharge cap |
| recovery.py + history.py | Forecast-based PV recovery, prior house consumption, expected SoC trough |
| migrate.py | Strict legacy night ledger migration + checksum manifest |
| status.py | Local read-only runtime status |
| public.py | Whitelisted read-only status/forecast export for an optional HA bridge |
| shadow.py | Offline comparison/observation utilities |
| predictive_observer.py | Preserved previous code (not active in beta's main control decision) |

## Control dataflow

1. EVCC REST provides actual charge and house-energy status.
2. The core guard verifies charging eligibility, metering coherence, sole battery-control ownership, SoC/BMS limits and Modbus availability. Classic protection **pre-arms** when the EVCC mode is deliberately set to fast with the vehicle attached; it does not wait for measured charger power to exceed a threshold. An *already active* cap is retained during EVCC shutdown mode transitions while the EV is still charging.
3. The intelligent worker starts only after protection readiness. It can issue a narrowly scoped short-lived permission; **it never starts or stops a vehicle charge**.
4. The shared decision path computes the permitted maximum discharge, bounded by KOSTAL baseline / BMS / user policy.
5. Only protection.py sends a live 1040 Modbus write.
6. State, budget, forecast and status are persisted under a dedicated private state_dir. Informational exports go to /run/battery-control-guard and optionally to HA via a separate reader.

## Failure behavior

No current intelligent permission => ordinary battery protection, not a free EV energy grant. Invalid/missing forecast => no extra intelligent grant. Another service writer or an instance with the same lock directory => refuse start. Loss of EVCC coherence => conservative control behavior subject to real-world inverter control limitations.

The file lock is per state directory, not a distributed lock; the operator must still exclude any other unrelated Modbus control software.

## Key invariants

- EVCC remains the sole party that commands EV charging.
- The guard does not modify EVCC charge schedules simply because a car was plugged in.
- No replenishment of spent night budgets after restart or migration.
- KOSTAL minimum SoC and battery BMS limits remain constraints.
- An active fallback on register 1040 is NOT equivalent to physical electric circuit isolation.
