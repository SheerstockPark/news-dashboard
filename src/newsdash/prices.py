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

# Energy equities an oil desk watches alongside the curve.
EQUITIES = [
    ("XLE", "Energy ETF", ""),
    ("XOM", "Exxon", ""),
    ("CVX", "Chevron", ""),
    ("SHEL", "Shell", ""),
    ("BP", "BP", ""),
    ("OXY", "Occidental", ""),
    ("HAL", "Halliburton", ""),
    ("^VIX", "VIX", ""),
]


def get_quotes(instruments=None) -> List[Dict]:
    """Return a list of quote dicts. Empty list if yfinance is unavailable."""
    try:
        import yfinance as yf
    except Exception:
        return []

    out: List[Dict] = []
    for symbol, label, unit in (instruments or INSTRUMENTS):
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


def get_spreads() -> List[Dict]:
    """Key oil spreads traders watch. Fails soft to []."""
    q = {x["symbol"]: x for x in get_quotes(INSTRUMENTS)}
    out = []
    brent, wti = q.get("BZ=F"), q.get("CL=F")
    if brent and wti:
        bw = round(brent["last"] - wti["last"], 2)
        out.append({"label": "Brent–WTI", "value": bw, "unit": "$/bbl",
                    "dir": "up" if bw >= 0 else "down"})
    # Simplified 3:2:1 crack spread (gasoline 2x + heating oil 1x, vs WTI), $/bbl
    rb, ho = q.get("RB=F"), q.get("CL=F")
    gas, heat = q.get("RB=F"), q.get("HO=F")
    if gas and heat and wti:
        crack = round((2 * gas["last"] * 42 + heat["last"] * 42) / 3 - wti["last"], 2)
        out.append({"label": "3:2:1 Crack", "value": crack, "unit": "$/bbl",
                    "dir": "up" if crack >= 0 else "down"})
    return out


def get_history(symbols, period="1d", interval="5m"):
    """Return {symbol: [(iso_minute, close), ...]} intraday series. Fails soft to {}."""
    try:
        import yfinance as yf
    except Exception:
        return {}
    out = {}
    for sym in symbols:
        try:
            h = yf.Ticker(sym).history(period=period, interval=interval)
            if h is None or h.empty:
                continue
            out[sym] = [(ts.isoformat(), round(float(c), 2))
                        for ts, c in h["Close"].dropna().items()]
        except Exception:
            continue
    return out
