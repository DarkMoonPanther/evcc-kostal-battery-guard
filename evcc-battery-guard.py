#!/usr/bin/env python3
"""Dynamic KOSTAL battery discharge limiter for EV fast/planned charging.

Design goals:
- outside evcc: only read evcc state, write one documented KOSTAL register (1040)
- never fight evcc: requires batteryDischargeControl=false before it will write
- never relax an existing inverter limit: dynamic target is capped by the baseline 1040
- fail conservative: incoherent/invalid state while active -> 1040=0 W
- relinquish 1040 control when guarded charging ends; inverter timeout handles failback
- no third-party Python dependencies
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import socket
import struct
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "0.3.0"
REG_BYTE_ORDER = 5
REG_MAX_DISCHARGE = 1040
REG_MIN_SOC = 1042
REG_BMS_MAX_DISCHARGE = 1078


def log(message: str, level: str = "INFO") -> None:
    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    print(f"{ts} {level} {message}", flush=True)


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name}: invalid boolean {raw!r}")


def env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Config:
    armed: bool
    evcc_state_url: str
    kostal_host: str
    kostal_port: int
    kostal_unit: int
    poll_interval_s: float
    refresh_interval_s: float
    min_change_w: float
    grid_margin_w: float
    min_charge_power_w: float
    min_soc_hysteresis_pct: float
    state_coherence_w: float
    readback_tolerance_w: float
    max_reasonable_power_w: float
    http_timeout_s: float
    modbus_timeout_s: float
    state_dir: Path

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            armed=env_bool("ARMED", False),
            evcc_state_url=os.getenv("EVCC_STATE_URL", "http://127.0.0.1:7070/api/state"),
            kostal_host=os.getenv("KOSTAL_HOST", ""),
            kostal_port=env_int("KOSTAL_PORT", 1502),
            kostal_unit=env_int("KOSTAL_UNIT", 71),
            poll_interval_s=env_float("POLL_INTERVAL_S", 5.0),
            refresh_interval_s=env_float("REFRESH_INTERVAL_S", 20.0),
            min_change_w=env_float("MIN_CHANGE_W", 100.0),
            grid_margin_w=env_float("GRID_MARGIN_W", 100.0),
            min_charge_power_w=env_float("MIN_CHARGE_POWER_W", 500.0),
            min_soc_hysteresis_pct=env_float("MIN_SOC_HYSTERESIS_PCT", 0.5),
            state_coherence_w=env_float("STATE_COHERENCE_W", 500.0),
            readback_tolerance_w=env_float("READBACK_TOLERANCE_W", 50.0),
            max_reasonable_power_w=env_float("MAX_REASONABLE_POWER_W", 30000.0),
            http_timeout_s=env_float("HTTP_TIMEOUT_S", 3.0),
            modbus_timeout_s=env_float("MODBUS_TIMEOUT_S", 3.0),
            state_dir=Path(os.getenv("STATE_DIR", "/var/lib/evcc-battery-guard")),
        )


class ModbusError(RuntimeError):
    pass


class ModbusTCP:
    """Minimal Modbus/TCP client implementing FC03 and FC16."""

    def __init__(self, host: str, port: int, unit: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.unit = unit
        self.timeout = timeout
        self._tid = 0

    @staticmethod
    def _recv_exact(sock: socket.socket, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                raise ModbusError("connection closed before complete response")
            data.extend(chunk)
        return bytes(data)

    def _request(self, function: int, payload: bytes) -> bytes:
        self._tid = (self._tid + 1) & 0xFFFF
        if self._tid == 0:
            self._tid = 1
        pdu = bytes([function]) + payload
        adu = struct.pack(">HHHB", self._tid, 0, len(pdu) + 1, self.unit) + pdu

        with socket.create_connection((self.host, self.port), self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(adu)
            header = self._recv_exact(sock, 7)
            tid, protocol, length, unit = struct.unpack(">HHHB", header)
            if tid != self._tid or protocol != 0 or unit != self.unit:
                raise ModbusError(
                    f"invalid MBAP response tid={tid} protocol={protocol} unit={unit}"
                )
            if length < 2:
                raise ModbusError(f"invalid MBAP length {length}")
            response = self._recv_exact(sock, length - 1)

        response_fc = response[0]
        if response_fc == (function | 0x80):
            code = response[1] if len(response) > 1 else -1
            raise ModbusError(f"Modbus exception function=0x{function:02x} code={code}")
        if response_fc != function:
            raise ModbusError(
                f"unexpected function in response: 0x{response_fc:02x}, expected 0x{function:02x}"
            )
        return response

    def read_holding(self, address: int, count: int) -> list[int]:
        response = self._request(0x03, struct.pack(">HH", address, count))
        expected_bytes = count * 2
        if len(response) != expected_bytes + 2 or response[1] != expected_bytes:
            raise ModbusError("malformed FC03 response")
        return list(struct.unpack(">" + "H" * count, response[2:]))

    def write_multiple(self, address: int, words: list[int]) -> None:
        count = len(words)
        data = struct.pack(">" + "H" * count, *words)
        payload = struct.pack(">HHB", address, count, len(data)) + data
        response = self._request(0x10, payload)
        if len(response) != 5:
            raise ModbusError("malformed FC16 response")
        start, written = struct.unpack(">HH", response[1:])
        if start != address or written != count:
            raise ModbusError(
                f"FC16 verification mismatch start={start} count={written}"
            )


class Kostal:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.bus = ModbusTCP(
            cfg.kostal_host, cfg.kostal_port, cfg.kostal_unit, cfg.modbus_timeout_s
        )
        self.byte_order: int | None = None

    def detect_byte_order(self) -> int:
        value = self.bus.read_holding(REG_BYTE_ORDER, 1)[0]
        if value not in (0, 1):
            raise ModbusError(f"unsupported KOSTAL byte-order register value {value}")
        self.byte_order = value
        return value

    def _require_order(self) -> int:
        if self.byte_order is None:
            return self.detect_byte_order()
        return self.byte_order

    def decode_float(self, words: list[int]) -> float:
        if len(words) != 2:
            raise ValueError("float requires exactly two Modbus registers")
        order = self._require_order()
        if order == 0:  # KOSTAL: little-endian CDAB (word-swapped)
            raw = struct.pack(">HH", words[1], words[0])
        else:  # KOSTAL: big-endian ABCD
            raw = struct.pack(">HH", words[0], words[1])
        value = struct.unpack(">f", raw)[0]
        if not math.isfinite(value):
            raise ModbusError("non-finite float read from inverter")
        return float(value)

    def encode_float(self, value: float) -> list[int]:
        if not math.isfinite(value):
            raise ValueError("refusing to encode non-finite float")
        order = self._require_order()
        hi, lo = struct.unpack(">HH", struct.pack(">f", float(value)))
        return [lo, hi] if order == 0 else [hi, lo]

    def read_float(self, address: int) -> float:
        return self.decode_float(self.bus.read_holding(address, 2))

    def write_float(self, address: int, value: float) -> float:
        if value < 0 or value > self.cfg.max_reasonable_power_w:
            raise ValueError(f"refusing out-of-range power limit {value:.1f} W")
        self.bus.write_multiple(address, self.encode_float(value))
        readback = self.read_float(address)
        if abs(readback - value) > self.cfg.readback_tolerance_w:
            raise ModbusError(
                f"write verification failed at {address}: requested={value:.1f} read={readback:.1f}"
            )
        return readback


def fetch_evcc_state(cfg: Config) -> dict[str, Any]:
    request = urllib.request.Request(cfg.evcc_state_url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=cfg.http_timeout_s) as response:
            if response.status != 200:
                raise RuntimeError(f"evcc returned HTTP {response.status}")
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"evcc state unavailable: {exc}") from exc

    if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
        payload = payload["result"]
    if not isinstance(payload, dict):
        raise RuntimeError("evcc state is not a JSON object")
    if payload.get("apiReady") is False:
        raise RuntimeError("evcc API reports apiReady=false")
    return payload


def number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"evcc field {name} is not numeric")
    value = float(value)
    if not math.isfinite(value):
        raise RuntimeError(f"evcc field {name} is not finite")
    return value


def battery_power(state: dict[str, Any]) -> float:
    battery = state.get("battery")
    if isinstance(battery, dict):
        return number(battery.get("power"), "battery.power")
    if isinstance(battery, list):
        return sum(number(item.get("power"), "battery[].power") for item in battery if isinstance(item, dict))
    raise RuntimeError("evcc battery state unavailable")


def battery_soc(state: dict[str, Any]) -> float:
    battery = state.get("battery")
    if isinstance(battery, dict):
        soc = number(battery.get("soc"), "battery.soc")
        if not (0.0 <= soc <= 100.0):
            raise RuntimeError(f"evcc battery.soc outside 0..100: {soc}")
        return soc
    raise RuntimeError("evcc battery SoC unavailable")


def pv_power(state: dict[str, Any]) -> float:
    pv = state.get("pv")
    if isinstance(pv, list):
        return max(0.0, sum(number(item.get("power"), "pv[].power") for item in pv if isinstance(item, dict)))
    if "pvPower" in state:
        return max(0.0, number(state.get("pvPower"), "pvPower"))
    return 0.0


def loadpoints(state: dict[str, Any]) -> list[dict[str, Any]]:
    value = state.get("loadpoints")
    if not isinstance(value, list):
        raise RuntimeError("evcc loadpoints unavailable")
    return [item for item in value if isinstance(item, dict)]


def protected_fast_charge(lp: dict[str, Any], cfg: Config) -> bool:
    if lp.get("charging") is not True:
        return False
    try:
        charge = number(lp.get("chargePower", 0), "loadpoint.chargePower")
    except RuntimeError:
        return False
    if charge < cfg.min_charge_power_w:
        return False
    return (
        lp.get("mode") == "now"
        or lp.get("planActive") is True
        or lp.get("minSocNotReached") is True
        or lp.get("smartCostActive") is True
    )


def metrics(state: dict[str, Any], cfg: Config) -> dict[str, Any]:
    lps = loadpoints(state)
    pv = pv_power(state)
    home = number(state.get("homePower"), "homePower")
    grid_obj = state.get("grid")
    if not isinstance(grid_obj, dict):
        raise RuntimeError("evcc grid state unavailable")
    grid = number(grid_obj.get("power"), "grid.power")
    battery = battery_power(state)
    soc = battery_soc(state)
    charge = sum(number(lp.get("chargePower", 0), "loadpoint.chargePower") for lp in lps)
    recomputed_home = grid + pv + battery - charge
    coherence_error = abs(recomputed_home - home)

    return {
        "home": home,
        "pv": pv,
        "grid": grid,
        "battery": battery,
        "battery_soc": soc,
        "charge": charge,
        "recomputed_home": recomputed_home,
        "coherence_error": coherence_error,
        "coherent": coherence_error <= cfg.state_coherence_w,
        "guard_requested": any(protected_fast_charge(lp, cfg) for lp in lps),
        "battery_boost": any(lp.get("batteryBoost") is True for lp in lps),
    }


class Guard:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.kostal = Kostal(cfg)
        self.stop_requested = False
        self.baseline: float | None = None
        self.last_target: float | None = None
        self.last_write_monotonic = 0.0
        self.min_soc_blocked = False
        self.last_min_soc_message: str | None = None
        self.session_file = cfg.state_dir / "session.json"

    def _save_session(self) -> None:
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "version": VERSION,
            "baseline_1040_w": self.baseline,
            "created": datetime.now(timezone.utc).isoformat(),
        }
        tmp = self.session_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.session_file)

    def _clear_session(self) -> None:
        try:
            self.session_file.unlink()
        except FileNotFoundError:
            pass

    def enter_session(self) -> bool:
        baseline = self.kostal.read_float(REG_MAX_DISCHARGE)
        bms_max = self.kostal.read_float(REG_BMS_MAX_DISCHARGE)
        if not (100.0 <= baseline <= self.cfg.max_reasonable_power_w):
            log(f"cannot arm session: baseline 1040={baseline:.1f} W is not a normal free limit", "WARN")
            return False
        if not (0.0 <= bms_max <= self.cfg.max_reasonable_power_w):
            log(f"cannot arm session: BMS max 1078={bms_max:.1f} W invalid", "WARN")
            return False
        self.baseline = baseline
        self.last_target = None
        self.last_write_monotonic = 0.0
        self._save_session()
        log(f"guard session started: baseline1040={baseline:.1f}W bmsMax1078={bms_max:.1f}W")
        return True

    def write_limit(self, target: float, reason: str) -> None:
        target = max(0.0, target)
        if self.baseline is not None:
            target = min(target, self.baseline)
        bms_max = max(0.0, self.kostal.read_float(REG_BMS_MAX_DISCHARGE))
        target = min(target, bms_max, self.cfg.max_reasonable_power_w)
        target = math.floor(target / 10.0) * 10.0
        readback = self.kostal.write_float(REG_MAX_DISCHARGE, target)
        self.last_target = target
        self.last_write_monotonic = time.monotonic()
        log(f"1040={readback:.1f}W reason={reason} bmsMax={bms_max:.1f}W")

    def recover_session(self) -> None:
        if not self.session_file.exists():
            return
        data = json.loads(self.session_file.read_text(encoding="utf-8"))
        baseline = float(data["baseline_1040_w"])
        if not math.isfinite(baseline) or not (100.0 <= baseline <= self.cfg.max_reasonable_power_w):
            raise RuntimeError(f"invalid persisted baseline 1040={baseline!r}")
        self.baseline = baseline
        self.last_target = None
        self.last_write_monotonic = 0.0
        log(f"recovered interrupted guard session: baseline1040={baseline:.1f}W")

    def relinquish(self, reason: str) -> None:
        if self.baseline is None:
            return
        # KOSTAL's documented failback is timeout-based: stop refreshing the
        # external control register and let the inverter resume internal control.
        # Do NOT write a stale/high baseline here; that would start a fresh
        # external-control timeout and could relax a newer inverter-side limit.
        log(f"guard relinquished; no further 1040 writes reason={reason}")
        self.baseline = None
        self.last_target = None
        self.last_write_monotonic = 0.0
        self._clear_session()

    def should_refresh(self, target: float) -> bool:
        if self.last_target is None:
            return True
        if abs(target - self.last_target) >= self.cfg.min_change_w:
            return True
        return (time.monotonic() - self.last_write_monotonic) >= self.cfg.refresh_interval_s

    def min_soc_allows_discharge(self, battery_soc_pct: float, min_soc_pct: float) -> bool:
        if not (0.0 <= min_soc_pct <= 100.0):
            raise RuntimeError(f"KOSTAL register 1042 outside 0..100: {min_soc_pct}")
        if self.min_soc_blocked:
            release_at = min(100.0, min_soc_pct + self.cfg.min_soc_hysteresis_pct)
            if battery_soc_pct >= release_at:
                self.min_soc_blocked = False
                self.last_min_soc_message = None
                log(
                    f"battery SoC recovered above minimum: soc={battery_soc_pct:.1f}% "
                    f"minSoc1042={min_soc_pct:.1f}% hysteresis={self.cfg.min_soc_hysteresis_pct:.1f}pp"
                )
                return True
            return False
        if battery_soc_pct <= min_soc_pct:
            self.min_soc_blocked = True
            return False
        return True

    def log_min_soc_wait(self, battery_soc_pct: float, min_soc_pct: float) -> None:
        message = (
            f"waiting: battery at KOSTAL minimum SoC "
            f"soc={battery_soc_pct:.1f}% minSoc1042={min_soc_pct:.1f}% "
            f"resumeAt={min(100.0, min_soc_pct + self.cfg.min_soc_hysteresis_pct):.1f}%"
        )
        if message != self.last_min_soc_message:
            log(message)
            self.last_min_soc_message = message

    def run(self) -> int:
        if not self.cfg.armed:
            log("ARMED=false: service is intentionally disarmed; no Modbus write performed")
            return 0

        order = self.kostal.detect_byte_order()
        log(f"starting guard v{VERSION}; KOSTAL byte order={'CDAB' if order == 0 else 'ABCD'}")
        self.recover_session()

        while not self.stop_requested:
            try:
                state = fetch_evcc_state(self.cfg)

                if state.get("batteryDischargeControl") is not False:
                    self.relinquish("evcc batteryDischargeControl is not false")
                    log("waiting: evcc batteryDischargeControl must be false", "WARN")
                    time.sleep(self.cfg.poll_interval_s)
                    continue

                m = metrics(state, self.cfg)
                battery_mode = str(state.get("batteryMode", "unknown")).lower()
                conflict = (
                    state.get("batteryGridChargeActive") is True
                    or state.get("batteryGridDischargeActive") is True
                    or m["battery_boost"]
                    or battery_mode not in {"unknown", "normal", "none", ""}
                )

                if conflict:
                    self.relinquish(f"conflicting battery mode/state ({battery_mode})")
                    time.sleep(self.cfg.poll_interval_s)
                    continue

                if not m["guard_requested"]:
                    self.relinquish("no protected fast/planned charging")
                    time.sleep(self.cfg.poll_interval_s)
                    continue

                if not m["coherent"]:
                    if self.baseline is not None and self.should_refresh(0.0):
                        self.write_limit(0.0, f"failsafe incoherent evcc state error={m['coherence_error']:.0f}W")
                    else:
                        log(
                            f"waiting for coherent evcc state: error={m['coherence_error']:.0f}W",
                            "WARN",
                        )
                    time.sleep(self.cfg.poll_interval_s)
                    continue

                min_soc = self.kostal.read_float(REG_MIN_SOC)
                if not self.min_soc_allows_discharge(m["battery_soc"], min_soc):
                    self.relinquish(
                        f"battery at minimum SoC ({m['battery_soc']:.1f}% <= {min_soc:.1f}%)"
                    )
                    self.log_min_soc_wait(m["battery_soc"], min_soc)
                    time.sleep(self.cfg.poll_interval_s)
                    continue
                self.last_min_soc_message = None

                if self.baseline is None and not self.enter_session():
                    time.sleep(self.cfg.poll_interval_s)
                    continue

                desired = max(0.0, m["home"] - m["pv"] - self.cfg.grid_margin_w)
                desired = min(desired, self.baseline if self.baseline is not None else desired)
                if self.should_refresh(desired):
                    self.write_limit(
                        desired,
                        (
                            f"home={m['home']:.0f}W pv={m['pv']:.0f}W "
                            f"gridMargin={self.cfg.grid_margin_w:.0f}W "
                            f"car={m['charge']:.0f}W"
                        ),
                    )

            except Exception as exc:
                log(f"control-cycle error: {exc}", "ERROR")
                if self.baseline is not None:
                    try:
                        if self.should_refresh(0.0):
                            self.write_limit(0.0, "failsafe after control-cycle error")
                    except Exception as fail_exc:
                        log(f"failsafe write failed: {fail_exc}", "ERROR")

            time.sleep(self.cfg.poll_interval_s)

        self.relinquish("service stop")
        return 0


def check(cfg: Config) -> int:
    state = fetch_evcc_state(cfg)
    k = Kostal(cfg)
    order = k.detect_byte_order()
    limit = k.read_float(REG_MAX_DISCHARGE)
    min_soc = k.read_float(REG_MIN_SOC)
    bms_max = k.read_float(REG_BMS_MAX_DISCHARGE)
    m = metrics(state, cfg)
    candidate = max(0.0, m["home"] - m["pv"] - cfg.grid_margin_w)
    result = {
        "version": VERSION,
        "armed": cfg.armed,
        "evccBatteryDischargeControl": state.get("batteryDischargeControl"),
        "evccBatteryMode": state.get("batteryMode"),
        "guardRequested": m["guard_requested"],
        "stateCoherent": m["coherent"],
        "coherenceErrorW": round(m["coherence_error"], 1),
        "homePowerW": round(m["home"], 1),
        "pvPowerW": round(m["pv"], 1),
        "chargePowerW": round(m["charge"], 1),
        "batterySocPct": round(m["battery_soc"], 1),
        "kostalMinSocPct": round(min_soc, 1),
        "minSocReached": m["battery_soc"] <= min_soc,
        "minSocResumePct": round(min(100.0, min_soc + cfg.min_soc_hysteresis_pct), 1),
        "candidateLimitW": round(candidate, 1),
        "kostalByteOrder": "CDAB" if order == 0 else "ABCD",
        "register1040W": round(limit, 1),
        "register1042Pct": round(min_soc, 1),
        "register1078W": round(bms_max, 1),
    }
    print(json.dumps(result, indent=2))
    return 0


def clear_session(cfg: Config) -> int:
    session_file = cfg.state_dir / "session.json"
    if not session_file.exists():
        log("clear-session: no persisted session marker")
        return 0
    session_file.unlink()
    log("clear-session: persisted session marker removed; no Modbus write performed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="run controller loop")
    parser.add_argument("--check", action="store_true", help="read-only connectivity/sanity check")
    parser.add_argument("--clear-session", action="store_true", help="clear persisted session marker without Modbus write")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()

    if args.version:
        print(VERSION)
        return 0

    cfg = Config.from_env()

    if args.check:
        return check(cfg)
    if args.clear_session:
        return clear_session(cfg)
    if not args.run:
        parser.error("one of --run, --check, --clear-session or --version is required")

    guard = Guard(cfg)

    def stop_handler(signum: int, _frame: Any) -> None:
        log(f"signal {signum} received; stopping")
        guard.stop_requested = True

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    try:
        return guard.run()
    finally:
        if guard.baseline is not None:
            guard.relinquish("process finalizer")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"fatal: {exc}", "ERROR")
        sys.exit(1)
