# Installation — v0.8.0-beta (new hosts only)

**This beta can issue live inverter commands. A fast-charge pre-arm and dynamic register-1040 control with logged release have been physically verified on one G3 setup, but not on your hardware.** Positive intelligent plan-based battery energy release remains unvalidated with the unified beta. A qualified operator must validate all inverter and failure-recovery conditions before enabling control.

## Prerequisites

Linux with systemd and Python 3.11+; EVCC with correct /api/state signals; a KOSTAL inverter supporting the documented external battery-management Modbus TCP interface; local trusted network; no competing battery controller. **Ensure EVCC automatic Optimizer battery control is off (not battery/full)** and no separate EVCC discharge control or third-party Modbus writer owns register 1040. Intelligent mode additionally needs a single supported EVCC loadpoint, exact vehicle identity, history, forecast and correct SoC reserve. Confirm firmware, Modbus port/Unit ID and failback timeout.

## Safe local test, without inverter writes

~~~bash
python3 --version
cp config.example.toml config.toml
# Edit config.toml: choose a writable absolute application.state_dir.
# Keep execution="observe", armed=false.
python3 -m battery_control_guard.app --config config.toml --check-config
python3 -m battery_control_guard.app --config config.toml --observe
python3 -m unittest discover -s tests -v
sh install.sh --dry-run
~~~

Observe fetches EVCC state only, does not open Modbus and performs no EVCC POST. It creates local status in your configured state directory.

## Install inactive files (new host; no existing guard)

~~~bash
sudo sh install.sh --install
~~~

The installer creates the dedicated bcguard user, code under /opt/battery-control-guard, config under /etc/battery-control-guard/config.toml, and the systemd unit. It **does not start/enable** the guard. It refuses existing installations. Edit the configuration privately, preserving its root:bcguard-only permissions.

## Initialize an intelligent-mode ledger (only if really new)

If no intelligent budget has ever been granted and no legacy ledger exists:

~~~bash
sudo -u bcguard env PYTHONPATH=/opt/battery-control-guard \
  python3 -m battery_control_guard.migrate \
  --state-dir /var/lib/battery-control-guard --fresh
~~~

NEVER use --fresh when upgrading from an existing 0.6/0.7 night-budget controller. See [Migration](MIGRATION.md).

## Active mode must be explicitly authorized

The systemd unit uses --run, which refuses the disarmed example. Only after safety approval and when no car charge is in progress, an operator may deliberately set the two application values execution="active" and armed=true, and configure the inverter address and verified controls.

~~~bash
sudo systemctl daemon-reload
sudo systemctl start battery-control-guard.service
sudo systemctl status battery-control-guard.service
sudo journalctl -u battery-control-guard.service -n 80 --no-pager
~~~

Do not enable boot autostart until the physical baseline, discharge limit, SoC/BMS, stop behavior, EVCC ownership, communication failure and KOSTAL internal-control fallback are independently tested.

## Emergency stop

~~~bash
sudo systemctl stop battery-control-guard.service
~~~

Service stop is NOT a guarantee that KOSTAL clears the last value instantly. Observe actual device failback. For an existing installation use [Rollback](ROLLBACK.md). The optional HA export adapter is not installed by this script.
