from __future__ import annotations

import argparse
import time

import serial


def _send_command(port: serial.Serial, command: str, timeout: float = 2.0) -> list[str]:
    port.reset_input_buffer()
    port.write((command + "\n").encode("utf-8"))
    port.flush()
    deadline = time.monotonic() + timeout
    lines: list[str] = []
    while time.monotonic() < deadline:
        raw = port.readline()
        if not raw:
            continue
        text = raw.decode("utf-8", errors="replace").strip()
        if text:
            lines.append(text)
            if text.startswith("{"):
                break
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision CCTV/RuView ESP32-S3 node over serial")
    parser.add_argument("--port", required=True, help="Serial port, for example COM3")
    parser.add_argument("--node-id", required=True, type=int, choices=range(1, 256))
    parser.add_argument("--ssid", default="CCTV-STAND")
    parser.add_argument("--password", default=None)
    parser.add_argument("--target-ip", default="192.168.88.10")
    parser.add_argument("--target-port", type=int, default=5005)
    parser.add_argument("--channel", type=int, default=11)
    parser.add_argument("--tdm-total", type=int, default=6)
    parser.add_argument("--tdm-slot", type=int, default=None)
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    tdm_slot = args.tdm_slot if args.tdm_slot is not None else args.node_id - 1
    label = f"cctv-ruview-node-{args.node_id:02d}"
    commands = [
        ("node_id", str(args.node_id)),
        ("label", label),
        ("ssid", args.ssid),
        ("target_ip", args.target_ip),
        ("target_port", str(args.target_port)),
        ("channel", str(args.channel)),
        ("tdm_total", str(args.tdm_total)),
        ("tdm_slot", str(tdm_slot)),
    ]
    if args.password is not None:
        commands.insert(3, ("password", args.password))

    print(f"Provisioning node {args.node_id} on {args.port}")
    print(f"TDM: slot={tdm_slot} total={args.tdm_total}, target={args.target_ip}:{args.target_port}")

    with serial.Serial(args.port, args.baud, timeout=0.2) as port:
        time.sleep(2.0)
        for key, value in commands:
            lines = _send_command(port, f"SET {key} {value}")
            print(f"SET {key}: {' | '.join(lines[-2:]) if lines else 'no response'}")
        print("SHOW:")
        for line in _send_command(port, "SHOW", timeout=3.0):
            print(line)
        _send_command(port, "REBOOT", timeout=0.5)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
