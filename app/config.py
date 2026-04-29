from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Drink(BaseModel):
    id: str
    name: str
    emoji: str
    price_usd: float
    description: str = ""


class DrinksConfig(BaseModel):
    drinks: list[Drink]
    topup_amounts_usd: list[float]
    low_balance_threshold_usd: float

    def get(self, drink_id: str) -> Drink | None:
        for d in self.drinks:
            if d.id == drink_id:
                return d
        return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    lnbits_url: str = "http://lnbits:5000"
    lnbits_admin_key: str = ""

    relay_driver: str = "simulator"
    shelly_host: str = ""
    grinder_pulse_seconds: int = 30

    drinks_config: str = "/app/drinks.yaml"
    database_path: str = "/data/espresso.sqlite3"

    btc_usd_rate: float = 50000.0


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_drinks() -> DrinksConfig:
    settings = get_settings()
    raw = yaml.safe_load(Path(settings.drinks_config).read_text())
    return DrinksConfig(**raw)


def usd_to_sats(usd: float, btc_usd: float | None = None) -> int:
    """Convert USD to integer satoshis at the configured rate.

    For a real production deployment this should hit a live price feed; for an
    espresso club where prices are cents, a configured rate is fine and gives
    you predictability. Tune via BTC_USD_RATE env var.
    """
    rate = btc_usd if btc_usd is not None else get_settings().btc_usd_rate
    sats_per_usd = 100_000_000 / rate
    return int(round(usd * sats_per_usd))


def sats_to_usd(sats: int, btc_usd: float | None = None) -> float:
    rate = btc_usd if btc_usd is not None else get_settings().btc_usd_rate
    return (sats / 100_000_000) * rate
