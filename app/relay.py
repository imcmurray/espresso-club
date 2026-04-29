"""Grinder relay control.

Two drivers:
- "simulator" — logs the pulse and waits. Used when no hardware is connected.
- "shelly"   — hits the Shelly Plus 1 HTTP API to switch the relay on for
               GRINDER_PULSE_SECONDS, then off.

The relay is wired in series with the grinder's power. When asserted, the
grinder can be operated normally; when off, the grinder is dead.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


class Relay:
    async def pulse(self, seconds: int) -> None:
        raise NotImplementedError


class SimulatorRelay(Relay):
    def __init__(self) -> None:
        self.last_pulse_seconds: int | None = None
        self.pulse_count = 0

    async def pulse(self, seconds: int) -> None:
        self.pulse_count += 1
        self.last_pulse_seconds = seconds
        logger.info("[SIM] grinder relay ON for %d seconds (pulse #%d)",
                    seconds, self.pulse_count)
        # We don't actually await here in the request path — the simulator
        # returns immediately so the UI feels real. In production the Shelly
        # driver also returns immediately and the relay self-times.


class ShellyRelay(Relay):
    """Shelly Plus 1 (Gen 2) HTTP API.

    See: https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/Switch
    Endpoint:  GET /rpc/Switch.Set?id=0&on=true&toggle_after=<seconds>
    """

    def __init__(self, host: str, *, channel: int = 0):
        self.host = host
        self.channel = channel

    async def pulse(self, seconds: int) -> None:
        url = (f"http://{self.host}/rpc/Switch.Set"
               f"?id={self.channel}&on=true&toggle_after={seconds}")
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
            r.raise_for_status()
        logger.info("Shelly relay pulsed for %d seconds at %s", seconds, self.host)


def make_relay(driver: str, shelly_host: str = "") -> Relay:
    if driver == "simulator":
        return SimulatorRelay()
    if driver == "shelly":
        if not shelly_host:
            raise ValueError("RELAY_DRIVER=shelly requires SHELLY_HOST to be set")
        return ShellyRelay(shelly_host)
    raise ValueError(f"unknown relay driver: {driver!r}")
