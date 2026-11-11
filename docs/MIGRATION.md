# Migration from the former guard to v0.8.0-beta

**Breaking change: not a drop-in update.** The public v0.4.0 used a single Python file, a .conf environment file and a different systemd service. This beta uses a Python package, TOML, a new systemd unit and (in intelligent mode) a migration-validated night budget. Do not copy the old config into the new installation.

## Safe invariants

1. No EV charge in progress during installation or switchover.
2. Back up legacy program, config, service, ledgers and recovery instructions privately.
3. Stop and disable EVERY previous battery controller before the new active start, including EVCC active battery control, third-party scripts and the old legacy service.
4. Never run two writers to KOSTAL register 1040 simultaneously.
5. Never reset an existing night ledger to enable further EV discharge.
6. Confirm actual physical fallback, not just a returned HTTP or Modbus status.

## A. Upgrading the public v0.4.0 (protection only)

Typical old public service name: evcc-battery-guard.service. The private development variant used mokka-battery-guard.service. These are distinct and both are recognized as legacy services by the prepared beta.

- Confirm the old installation is actually v0.4.0, inspect its systemd unit and safely back up all files outside Git.
- When there is no active EV charge, disable/stop the old guard. Verify service inactive and disabled. Inspect other writers separately.
- Install the new beta using the new installation guide. The installer refuses if a new target already exists; it does not modify the old files.
- Configure protection mode, EVCC and KOSTAL paths using config.example.toml, first disarmed and in observation mode. Confirm all values before allowing active operation.
- The v0.4.0 *protection-only* implementation has no intelligent night budget to transfer. If and only if there is no other historic intelligent budget, a fresh marker may be used when switching on intelligent mode in the future.
- Enable/start the new service only once old control is stopped, hardware failback is understood and live commissioning is supervised.
- Keep the old v0.4.0 backup and Git tag as the rollback route. See [Rollback](ROLLBACK.md).

## B. Upgrading the private 0.6.2 / 0.7.2 integrated setup

The old standalone guard and forecast controller operated as separate processes. The 0.7.2 controller had night ledgers; the previous active charging behavior also differed and could start a charge when plugging in a vehicle.

**Do NOT restart the old intelligent controller as an automatic rollback.** Its EVCC-charge authority differs from v0.8.0.

- Stop and disable old guard and the old 0.7.2 user systemd controller. Verify no old process remains and no planned EV charging is active.
- Preserve the original night-ledger directory and current session file; do not edit them.
- Run the migration module OFFLINE, with the old controller root supplied as an explicit path. It copies the legacy ledger and session into the NEW state directory and records SHA256 checksums. Originals are never deleted.
- The current migration module expects the historic relative layout phase3-results/night-ledgers-v070 and phase3-results/intelligent-session.json. If the original layout differs, stop; do not invent a fresh ledger.
- For the packaged system, run migration under the new dedicated service account and supply PYTHONPATH pointing to the installed code. Example (substitute YOUR actual old root):

~~~bash
sudo -u bcguard env PYTHONPATH=/opt/battery-control-guard \
  python3 -m battery_control_guard.migrate \
  --state-dir /var/lib/battery-control-guard \
  --source /path/to/your/legacy-controller-root
~~~

- Migration must be done once, with no controller active. If a migration marker already exists, the program refuses overwrite. Investigate rather than delete/reinitialize.
- Start in protection-only mode first; enable intelligent mode only once the ledger validation, reserve data, matching EVCC vehicle identity and full permission lifecycle have been verified.

## About configuration and privileges

The public v0.4.0 and new v0.8.0 TOML schemas are incompatible. An old EVCC config or host address must be reviewed and manually transferred field by field, never published.

The new unit runs as a dedicated service user and applies ProtectHome=yes; HA token files under a user's home are not readable. Use a private service-readable path outside the home directory if HA reserve is enabled.

## After migration

Verify live measured KOSTAL 1040 behavior, KOSTAL min SoC and BMS caps, EVCC charging ownership, no spontaneous vehicle charge, budget without duplicate allocations, stale forecast rejection and release to internal control after charging. Document a return path before approving autostart.

**Historical versions remain available through Git tags**, but the old single-file installer is not part of the new main branch.
