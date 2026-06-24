"""Live commodity/FX quotes for the dashboard ticker.

Thin wrapper over yfinance. Returns last price + change vs previous close for the
instruments an oil desk watches. Fails soft: a quote that can't be fetched is omitted
rather than raising, so a Yahoo hiccup never takes down the dashboard.
"""

from typing import Dict, List

# (yfinance symbol, display label, unit)
INSTRUMENTS = [
    ("BZ=F", "Brent", "$/bbl"),
    ("CL=F", "WTI", "$/bbl"),
    ("NG=F", "Nat Gas", "$/MMBtu"),
    ("RB=F", "Gasoline", "$/gal"),
    ("HO=F", "Heating Oil", "$/gal"),
    ("DX-Y.NYB", "Dollar Index", ""),
]


def get_quotes() -> List[Dict]:
    """Return a list of quote dicts. Empty list if yfinance is unavailable."""
    try:
        import yfinance as yf
    except Exception:
        return []

    out: List[Dict] = []
    for symbol, label, unit in INSTRUMENTS:
        try:
            fi = yf.Ticker(symbol).fast_info
            last = float(fi.last_price)
            prev = float(fi.previous_close)
            if not last or not prev:
                continue
            change = last - prev
            pct = (change / prev * 100.0) if prev else 0.0
            out.append(
                {
                    "symbol": symbol,
                    "label": label,
                    "unit": unit,
                    "last": round(last, 2),
                    "change": round(change, 2),
                    "pct": round(pct, 2),
                    "dir": "up" if change > 0 else "down" if change < 0 else "flat",
                }
            )
        except Exception:
            continue  # skip this instrument, keep the rest
    return out
