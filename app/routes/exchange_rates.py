"""
AirEase Backend - Exchange Rates Route
Provides live currency exchange rates using the CurrencyConverter library (offline ECB data).
Rates are cached in-memory for 1 hour to avoid repeated computation.
"""

import time
from fastapi import APIRouter
from typing import Dict

router = APIRouter(prefix="/v1/exchange-rates", tags=["Exchange Rates"])

# Target currencies we support (convert FROM USD to each)
SUPPORTED_CURRENCIES = [
    "USD", "CNY", "EUR", "GBP", "JPY",
    "HKD", "SGD", "AUD", "CAD", "KRW",
    "INR", "THB",
]

# In-memory cache: { "rates": {...}, "fetched_at": timestamp }
_cache: Dict = {}
CACHE_TTL_SECONDS = 3600  # 1 hour


def _fetch_rates() -> Dict[str, float]:
    """
    Fetch exchange rates from USD to all supported currencies
    using the CurrencyConverter library (ECB data, works offline).
    """
    from currency_converter import CurrencyConverter
    c = CurrencyConverter()

    rates: Dict[str, float] = {}
    for code in SUPPORTED_CURRENCIES:
        if code == "USD":
            rates["USD"] = 1.0
            continue
        try:
            rate = c.convert(1, "USD", code)
            # Round to reasonable precision
            rates[code] = round(rate, 4)
        except Exception:
            # If a currency isn't in the ECB dataset, use a sensible fallback
            rates[code] = _fallback_rate(code)

    return rates


def _fallback_rate(code: str) -> float:
    """Hardcoded fallback for currencies not covered by ECB data."""
    fallbacks = {
        "CNY": 7.25,
        "KRW": 1320.0,
        "INR": 83.5,
        "THB": 35.5,
        "HKD": 7.82,
        "SGD": 1.34,
    }
    return fallbacks.get(code, 1.0)


@router.get(
    "",
    summary="Get exchange rates from USD",
    description="Returns current exchange rates from USD to all supported currencies. "
                "Rates are sourced from ECB data and cached for 1 hour.",
)
async def get_exchange_rates():
    """
    Returns exchange rates from USD → all supported currencies.
    Response is cached in-memory for 1 hour.
    """
    global _cache

    now = time.time()
    if _cache and (now - _cache.get("fetched_at", 0)) < CACHE_TTL_SECONDS:
        return _cache["data"]

    rates = _fetch_rates()
    data = {
        "base": "USD",
        "rates": rates,
        "supported": SUPPORTED_CURRENCIES,
    }
    _cache = {"data": data, "fetched_at": now}
    return data
