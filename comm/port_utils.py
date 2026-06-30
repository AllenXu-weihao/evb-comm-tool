"""COM port enumeration helpers for Windows."""

from __future__ import annotations

import serial.tools.list_ports


def list_com_ports() -> list[dict]:
    """Return available COM ports with device metadata."""
    ports: list[dict] = []
    for info in serial.tools.list_ports.comports():
        ports.append(
            {
                "device": info.device,
                "description": info.description or "",
                "hwid": info.hwid or "",
                "manufacturer": info.manufacturer or "",
                "label": format_port_label(info),
            }
        )
    return ports


def format_port_label(info: serial.tools.list_ports.ListPortInfo) -> str:
    """Build a user-friendly dropdown label."""
    desc = (info.description or "").strip()
    if desc and desc.lower() not in info.device.lower():
        return f"{info.device} - {desc}"
    return info.device


def format_port_log_line(port: dict) -> str:
    """Format one port for log output."""
    parts = [port["device"]]
    if port["description"]:
        parts.append(port["description"])
    if port["hwid"]:
        parts.append(f"[{port['hwid']}]")
    return "  ".join(parts)
