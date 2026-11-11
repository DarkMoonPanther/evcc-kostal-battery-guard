# Rollback / recovery — v0.8.0-beta

This is an operator procedure, NOT an automatic universal rollback script. The separate private development cutover script was written for one specific Raspberry Pi and is deliberately **not** distributed.

## Preconditions

Before starting the beta, retain backups of the old software/config, systemd unit, EVCC/HA settings, and all night budget ledgers. Verify the KOSTAL external-control timeout and the expected return to internal battery regulation. Keep a competent local operator available.

## Controlled stop

1. Avoid an active EV charging session and identify whether battery discharge is currently limited by v0.8.0.
2. Stop and disable the **new** battery-control-guard.service.
3. Confirm it is inactive, its process and instance lock are gone, and no other writer is automatically running.
4. Observe KOSTAL return to internal control through the actual measured battery behavior and 1040 readback. Stopping writes is not an immediate guarantee that the inverter has restored its normal control.
5. Investigate unexpected battery behavior before enabling any other control software.

~~~bash
sudo systemctl disable --now battery-control-guard.service
systemctl is-active battery-control-guard.service
sudo journalctl -u battery-control-guard.service -n 80 --no-pager
~~~

## Restore an earlier installation (only one active writer)

- A former **public v0.4.0** installation may be restored from its private backup with the original configuration and service unit. Start it only after new v0.8.0 control has been fully stopped.
- A former **local 0.6.2/0.7.2** installation should restore the classical **protection-only** guard, with the old intelligent controller left disabled until separately reviewed. The older intelligent component could initiate an EV charge on connection.
- Preserve v0.8.0 state and budget ledgers for forensic review; do not destroy/zero them as a shortcut.
- Do not let a restored guard and EVCC's active battery-discharge-control feature compete.

## Failure cases

- Communication or forecast failure: stop intelligent permission, retain an existing safe protection policy, then inspect actual state.
- Repeated unexpected 1040 writes: stop the new service, isolate external controllers, verify KOSTAL's own fallback.
- Physical power loss: the software cannot guarantee supply-side battery isolation; check the inverter/BMS safety and external-control settings.
- Unclear authorizations, wrong metering or vehicle identity: leave intelligent mode disabled.

Only resume autostart after a documented successful live acceptance test.
