from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import serial


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_layout(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _node_by_label(layout: dict, node_id: int) -> dict:
    for node in layout.get("nodes", []):
        if str(node.get("physical_label")) == str(node_id):
            return node
    raise SystemExit(f"Node with physical_label={node_id} not found in {path_hint(layout)}")


def path_hint(layout: dict) -> str:
    return layout.get("name") or "RF room layout"


def _peers_string(layout: dict) -> str:
    peers: list[str] = []
    for node in layout.get("nodes", []):
        label = str(node.get("physical_label", "")).strip()
        mac = str(node.get("mac", "")).strip().upper()
        ip = str(node.get("ip", "")).strip()
        if not label.isdigit() or not mac:
            continue
        item = f"{int(label)}@{mac}"
        if ip:
            item += f"@{ip}"
        peers.append(item)
    return ";".join(peers)


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
    parser = argparse.ArgumentParser(description="Provision CCTV RF CSI ESP32 node over serial")
    parser.add_argument("--port", required=True, help="Serial port, for example COM3")
    parser.add_argument("--node-id", required=True, type=int, choices=range(1, 256))
    parser.add_argument("--ssid", default="CCTV-STAND")
    parser.add_argument("--password", required=True)
    parser.add_argument("--target-ip", default="192.168.88.10")
    parser.add_argument("--target-port", type=int, default=5005)
    parser.add_argument("--channel", type=int, default=11)
    parser.add_argument("--tdm-total", type=int, default=6)
    parser.add_argument("--tdm-slot", type=int, default=None)
    parser.add_argument(
        "--layout",
        type=Path,
        default=_repo_root() / "config" / "rf_room_layout.json",
        help="RF room layout JSON used to generate peer MAC/IP list",
    )
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    layout = _load_layout(args.layout)
    node = _node_by_label(layout, args.node_id)
    tdm_slot = args.tdm_slot if args.tdm_slot is not None else args.node_id - 1
    peers = _peers_string(layout)
    label = f"cctv-rf-node-{args.node_id:02d}"

    commands = [
        ("node_id", str(args.node_id)),
        ("label", label),
        ("ssid", args.ssid),
        ("password", args.password),
        ("target_ip", args.target_ip),
        ("target_port", str(args.target_port)),
        ("channel", str(args.channel)),
        ("tdm_total", str(args.tdm_total)),
        ("tdm_slot", str(tdm_slot)),
        ("peers", peers),
    ]

    print(f"Provisioning node {args.node_id} on {args.port}")
    print(f"Layout node: {node.get('node_id')} mac={node.get('mac')} ip={node.get('ip')}")
    print(f"TDM: slot={tdm_slot} total={args.tdm_total}, peers={len([p for p in peers.split(';') if p])}")

    with serial.Serial(args.port, args.baud, timeout=0.2) as port:
        time.sleep(2.0)
        for key, value in commands:
            lines = _send_command(port, f"SET {key} {value}")
            print(f"SET {key}: {' | '.join(lines[-2:]) if lines else 'no response'}")
        lines = _send_command(port, "SHOW", timeout=3.0)
        print("SHOW:")
        for line in lines:
            print(line)
        _send_command(port, "REBOOT", timeout=0.5)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
