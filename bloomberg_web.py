"""
Vinny's Stock Intelligence Terminal — Web Edition
FastAPI backend · Vinny's dark UI · Auto-refresh every 5 min
Run:  python bloomberg_web.py   →   open http://localhost:8000
"""

import io
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta
try:
    from zoneinfo import ZoneInfo as _ZI
    _ET = _ZI("America/New_York")
    def _et_now(): return datetime.now(_ET).replace(tzinfo=None)
except ImportError:
    def _et_now():
        utc  = datetime.utcnow()
        yr   = utc.year
        dst_start = datetime(yr, 3,  8) + timedelta(days=(6 - datetime(yr, 3,  8).weekday()) % 7)
        dst_end   = datetime(yr, 11, 1) + timedelta(days=(6 - datetime(yr, 11, 1).weekday()) % 7)
        return utc + timedelta(hours=-4 if dst_start <= utc < dst_end else -5)

import numpy as np
import requests
import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, Response
from pypdf import PdfReader

# ── Config ──────────────────────────────────────────────────────────────────────
POLYGON_BASE    = "https://api.polygon.io"
POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "OehRygcqWPd78jOSWTBgfhu9oCsBqxcw")

LAUNCHPAD_INDICES = [
    # symbol=None → section header row (no fetch)
    # Stocks/ETFs use Polygon stock snapshot; C: = forex; X: = crypto
    (None,         "── INDICES ──"),
    ("DIA",        "DOW JONES"),      # Dow Jones ETF
    ("SPY",        "S&P 500"),        # S&P 500 ETF
    ("QQQ",        "NASDAQ"),         # NASDAQ ETF
    ("IWM",        "RUSSELL 2K"),     # Russell 2000 ETF
    ("VIXY",       "VIX"),            # VIX ETF
    ("TLT",        "10Y YIELD"),      # 20yr Treasury ETF
    (None,         "── COMMODITIES ──"),
    ("GLD",        "GOLD"),           # Gold ETF
    ("SLV",        "SILVER"),         # Silver ETF
    ("USO",        "CRUDE OIL"),      # Crude Oil ETF
    ("UNG",        "NAT GAS"),        # Nat Gas ETF
    ("COPX",       "COPPER"),         # Copper ETF
    (None,         "── CURRENCIES ──"),
    ("UUP",        "USD INDEX"),      # USD Index ETF
    ("C:EURUSD",   "EUR / USD"),
    ("C:GBPUSD",   "GBP / USD"),
    ("C:USDJPY",   "USD / JPY"),
    ("C:USDCHF",   "USD / CHF"),
    (None,         "── CRYPTO ──"),
    ("X:BTCUSD",   "BITCOIN"),
    ("X:ETHUSD",   "ETHEREUM"),
]

SECTORS = [
    ("XLK",  "Technology"),
    ("XLF",  "Financials"),
    ("XLV",  "Health Care"),
    ("XLE",  "Energy"),
    ("XLC",  "Communication"),
    ("XLI",  "Industrials"),
    ("XLY",  "Cons. Disc."),
    ("XLP",  "Cons. Staples"),
    ("XLB",  "Materials"),
    ("XLRE", "Real Estate"),
    ("XLU",  "Utilities"),
]
HEADERS          = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
REFRESH_INTERVAL  = 300
MAX_WORKERS       = 5    # keep within Polygon rate limits
SCORE_BUY         = 65
SCORE_WATCH       = 40
_POLY_SEMAPHORE   = threading.Semaphore(5)  # max 5 concurrent Polygon calls

# ── Universe ─────────────────────────────────────────────────────────────────────
DOW_30 = [
    "AAPL", "AMGN", "AMZN", "AXP",  "BA",   "CAT",  "CRM",  "CSCO", "CVX",  "DIS",
    "DOW",  "GS",   "HD",   "HON",  "IBM",  "JNJ",  "JPM",  "KO",   "MCD",  "MMM",
    "MRK",  "MSFT", "NKE",  "NVDA", "PG",   "TRV",  "UNH",  "V",    "VZ",   "WMT",
]

NASDAQ_100 = [
    "AAPL",  "MSFT",  "NVDA",  "AMZN",  "META",  "GOOGL", "GOOG",  "TSLA",  "AVGO",  "COST",
    "NFLX",  "ASML",  "AMD",   "ADBE",  "QCOM",  "INTU",  "AMAT",  "MU",    "BKNG",  "HON",
    "LRCX",  "SNPS",  "CDNS",  "ADI",   "KLAC",  "MDLZ",  "SBUX",  "GILD",  "REGN",  "MELI",
    "PANW",  "CRWD",  "MNST",  "CSX",   "ADP",   "MAR",   "ORLY",  "CTAS",  "FTNT",  "NXPI",
    "MRVL",  "PCAR",  "KDP",   "CHTR",  "DXCM",  "TEAM",  "DLTR",  "ABNB",  "BIIB",  "FAST",
    "IDXX",  "LULU",  "MCHP",  "ODFL",  "PAYX",  "ROST",  "VRSK",  "VRTX",  "WDAY",  "TTWO",
    "TTD",   "TMUS",  "EBAY",  "EXC",   "EA",    "DDOG",  "CMCSA", "CEG",   "CPRT",  "BKR",
    "AXON",  "ANSS",  "ON",    "GEHC",  "FANG",  "ILMN",  "ZS",    "INTC",  "PYPL",  "ISRG",
    "ROP",   "WBD",   "CCEP",  "GFS",   "ARM",   "PDD",   "CSGP",  "AMGN",  "SIRI",  "XEL",
    "AZN",   "APP",   "CDW",   "NTAP",  "ZM",    "SMCI",  "MSTR",  "PSTG",  "ZBRA",  "ALGN",
]

SP500_EXTRA = [
    "BRK-B", "JPM",  "BAC",  "WFC",  "MS",   "GS",   "C",    "BX",   "KKR",  "BLK",
    "SPGI",  "MCO",  "ICE",  "FI",   "COF",  "AXP",  "DFS",  "USB",  "PNC",  "TFC",
    "MTB",   "FITB", "KEY",  "RF",   "HBAN", "CFG",  "ALLY", "SYF",  "AIG",  "MET",
    "PRU",   "AFL",  "ALL",  "PGR",  "CB",   "TRV",  "AON",  "MMC",  "WTW",  "RE",
    "LLY",   "ABBV", "ABT",  "MDT",  "SYK",  "BSX",  "ELV",  "CI",   "HUM",  "CVS",
    "HCA",   "CNC",  "MOH",  "DHR",  "EW",   "RMD",  "ZBH",  "BDX",  "BAX",  "COO",
    "MTD",   "TFX",  "HOLX", "PODD", "VTRS", "JAZZ", "NBIX", "INCY", "ALNY", "BMRN",
    "XOM",   "CVX",  "COP",  "EOG",  "PSX",  "VLO",  "MPC",  "OXY",  "DVN",  "HAL",
    "SLB",   "BKR",  "HES",  "CTRA", "APA",  "MRO",  "NOV",  "FTI",  "WMB",  "OKE",
    "KMI",   "ET",   "EPD",  "LNG",  "TRGP",
    "RTX",   "GE",   "LMT",  "NOC",  "GD",   "L3H",  "TXT",  "HII",  "TDG",  "AXON",
    "UNP",   "FDX",  "UPS",  "DAL",  "UAL",  "LUV",  "AAL",  "JBLU", "WM",   "RSG",
    "ETN",   "EMR",  "NSC",  "GWW",  "ROK",  "PH",   "ITW",  "DOV",  "AME",  "XYL",
    "IEX",   "GNRC", "TT",   "CARR", "OTIS", "JCI",  "PWR",  "MTZ",  "FBIN", "MAS",
    "CMG",   "YUM",  "DPZ",  "DG",   "KR",   "SYY",  "RL",   "PVH",  "TPR",  "VFC",
    "HLT",   "H",    "WH",   "MGM",  "LVS",  "WYNN", "CZR",  "PENN", "DKNG", "BALY",
    "F",     "GM",   "STLA", "TM",   "HMC",  "AN",   "LAD",  "PAG",  "KMX",  "AZO",
    "ORLY",  "AAP",  "GPC",  "MNRO",
    "MO",    "PM",   "BTI",  "STZ",  "BUD",  "TAP",  "K",    "GIS",  "CPB",  "CAG",
    "SJM",   "MKC",  "HRL",  "TSN",  "PPC",  "SAFM", "WBA",  "RAD",  "CL",   "CHD",
    "CLX",   "PG",   "KMB",  "EL",   "COTY",
    "ORCL",  "ACN",  "HPQ",  "HPE",  "DELL", "WDC",  "STX",  "KEYS", "TDC",  "LDOS",
    "SAIC",  "CSRA", "DXC",  "EPAM", "CTSH", "WIT",  "INFY", "TCS",
    "LIN",   "APD",  "DD",   "NEM",  "FCX",  "NUE",  "STLD", "CLF",  "ALB",  "PPG",
    "EMN",   "CE",   "OLN",  "WLK",  "LYB",  "MOS",  "CF",   "FMC",  "IFF",  "SON",
    "PLD",   "AMT",  "EQIX", "SPG",  "O",    "VICI", "PSA",  "EXR",  "AVB",  "EQR",
    "ARE",   "WY",   "CBRE", "JLL",  "CCI",  "SBA",  "SBAC", "IRM",  "DLR",  "QTS",
    "NEE",   "DUK",  "SO",   "D",    "AEP",  "SRE",  "PCG",  "ED",   "ES",   "FE",
    "WEC",   "ETR",  "PPL",  "AEE",  "CNP",  "NI",   "CMS",  "PNW",  "EVRG", "AWK",
    "T",     "VZ",   "CMCSA","DIS",  "NFLX", "PARA", "FOX",  "NWS",  "NYT",  "IAC",
    "ZG",    "MTCH", "BMBL", "SNAP", "PINS",
]


def _build_universe():
    seen, result = set(), []
    for sym in DOW_30:
        if sym not in seen:
            seen.add(sym); result.append((sym, "DOW"))
    for sym in NASDAQ_100:
        if sym not in seen:
            seen.add(sym); result.append((sym, "NDAQ"))
    for sym in SP500_EXTRA:
        if sym not in seen:
            seen.add(sym); result.append((sym, "SP500"))
    return result


UNIVERSE = _build_universe()

# ── Shared State ─────────────────────────────────────────────────────────────────
_state = {
    "stocks":       {},
    "loading":      False,
    "loaded":       0,
    "total":        len(UNIVERSE),
    "last_updated": "Never",
    "error_count":  0,
    "next_refresh": 0.0,
}

# ── Indicator Engine ──────────────────────────────────────────────────────────────
def _ema(data, period):
    a = 2.0 / (period + 1)
    e = [data[0]]
    for v in data[1:]:
        e.append(a * v + (1.0 - a) * e[-1])
    return e


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    d  = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    ag = sum(max(v, 0) for v in d[-period:]) / period
    al = sum(max(-v, 0) for v in d[-period:]) / period
    return 100.0 if al == 0 else 100.0 - (100.0 / (1.0 + ag / al))


def _score(closes):
    if len(closes) < 35:
        return None
    price = closes[-1]
    ema20 = _ema(closes, 20)[-1]
    ema50 = _ema(closes, min(50, len(closes)))[-1]

    ema_s = 0
    if price > ema20:  ema_s += 8
    if price > ema50:  ema_s += 8
    if ema20  > ema50: ema_s += 4

    e12    = _ema(closes, 12)
    e26    = _ema(closes, 26)
    macd   = [a - b for a, b in zip(e12, e26)]
    sig    = _ema(macd, 9)
    hist   = macd[-1] - sig[-1]
    hist_p = macd[-2] - sig[-2] if len(macd) >= 2 else hist
    macd_s = 0
    if macd[-1] > sig[-1]: macd_s += 12
    if hist > hist_p:      macd_s += 8

    rsi = _rsi(closes)
    if   60 <= rsi <= 70: rsi_s = 20
    elif 40 <= rsi <  60: rsi_s = 13
    elif 70 <  rsi <= 80: rsi_s = 10
    elif 30 <= rsi <  40: rsi_s =  6
    else:                 rsi_s =  2

    w = closes[-20:] if len(closes) >= 20 else closes
    x = np.arange(len(w), dtype=float)
    sl, _ = np.polyfit(x, w, 1)
    sp_pct = (sl / w[0]) * 100 if w[0] else 0
    trend_s = 0
    if sl    > 0:    trend_s += 12
    if sp_pct > 0.3: trend_s += 8

    total = ema_s + macd_s + rsi_s + trend_s
    return {
        "ema_s": ema_s, "macd_s": macd_s, "rsi_s": rsi_s, "trend_s": trend_s,
        "total": total, "rsi": round(float(rsi), 1),
    }


def _analyst_score(mean):
    if mean is None:   return 10
    if mean <= 1.5:    return 20
    elif mean <= 2.0:  return 16
    elif mean <= 2.5:  return 12
    elif mean <= 3.0:  return  8
    elif mean <= 3.5:  return  4
    else:              return  2


def _fetch_analyst(sym):
    # Analyst consensus not available from Polygon; returns None so score is 0
    return None


def _bar(score, mx=20):
    filled = max(0, min(8, round(score / mx * 8)))
    return "\u2588" * filled + "\u2591" * (8 - filled)


def _fetch_one(sym, idx):
    try:
        today     = date.today()
        from_date = str(today - timedelta(days=90))
        to_date   = str(today)
        data  = _poly_get(
            f"{POLYGON_BASE}/v2/aggs/ticker/{sym}/range/1/day/{from_date}/{to_date}",
            params={"adjusted": "true", "sort": "asc", "limit": 500},
            timeout=20,
        )
        bars   = data.get("results") or []
        closes = [b["c"] for b in bars if b.get("c") is not None]
        sc     = _score(closes)
        if sc is None:
            return None
        analyst_s    = 0
        analyst_mean = None
        total  = sc["total"]
        signal = "BUY" if total >= SCORE_BUY else ("WATCH" if total >= SCORE_WATCH else "NO BUY")
        price  = closes[-1] if closes else 0.0
        return {
            "symbol":       sym,
            "name":         sym,
            "price":        round(price, 4),
            "index":        idx,
            "ema_s":        sc["ema_s"],
            "macd_s":       sc["macd_s"],
            "rsi_s":        sc["rsi_s"],
            "trend_s":      sc["trend_s"],
            "analyst_s":    analyst_s,
            "analyst_mean": analyst_mean,
            "total":        total,
            "rsi":          sc["rsi"],
            "signal":       signal,
            "bar_ema":      _bar(sc["ema_s"]),
            "bar_macd":     _bar(sc["macd_s"]),
            "bar_rsi":      _bar(sc["rsi_s"]),
            "bar_trend":    _bar(sc["trend_s"]),
            "bar_analyst":  "\u2591" * 8,
        }
    except Exception:
        return None


def _bg_refresh():
    _state["loading"]     = True
    _state["loaded"]      = 0
    _state["error_count"] = 0
    stocks = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one, s, i): s for s, i in UNIVERSE}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                stocks[res["symbol"]] = res
            else:
                _state["error_count"] += 1
            _state["loaded"] += 1
    _state["stocks"]       = stocks
    _state["last_updated"] = datetime.now().strftime("%H:%M:%S")
    _state["loading"]      = False
    _state["next_refresh"] = time.time() + REFRESH_INTERVAL


def trigger_refresh():
    if not _state["loading"]:
        threading.Thread(target=_bg_refresh, daemon=True).start()

# ── Polygon helper ───────────────────────────────────────────────────────────────
def _poly_get(url, params=None, timeout=15, retries=5):
    """GET a Polygon endpoint, retrying on 429 with exponential backoff."""
    p = {"apiKey": POLYGON_API_KEY, **(params or {})}
    for attempt in range(retries):
        r = requests.get(url, params=p, headers=HEADERS, timeout=timeout)
        if r.status_code == 429:
            time.sleep(2 ** attempt)   # 1 s, 2 s, 4 s, 8 s, 16 s
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Polygon rate-limited after {retries} retries: {url}")


def _market_open():
    """True when NYSE is open: Mon–Fri, 09:30–16:00 ET."""
    now = _et_now()
    if now.weekday() >= 5:                         # Saturday=5, Sunday=6
        return False
    open_t  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_t <= now <= close_t


# ── MACD Chart Data ──────────────────────────────────────────────────────────────
def _compute_chart_data(sym):
    """Fetch 6 months of OHLCV data and return full indicator series for charting."""
    today     = date.today()
    from_date = str(today - timedelta(days=180))
    to_date   = str(today)
    data = _poly_get(
        f"{POLYGON_BASE}/v2/aggs/ticker/{sym}/range/1/day/{from_date}/{to_date}",
        params={"adjusted": "true", "sort": "asc", "limit": 500},
        timeout=20,
    )
    bars = data.get("results") or []

    rows = []
    for b in bars:
        if any(b.get(k) is None for k in ["o", "h", "l", "c"]):
            continue
        dt = datetime.utcfromtimestamp(b["t"] / 1000).strftime("%Y-%m-%d")
        rows.append((dt, float(b["o"]), float(b["h"]), float(b["l"]), float(b["c"]), int(b.get("v") or 0)))

    if len(rows) < 35:
        return None

    dates  = [r[0] for r in rows]
    closes = [r[4] for r in rows]

    ema20v = _ema(closes, 20)
    ema50v = _ema(closes, min(50, len(closes)))
    ema12  = _ema(closes, 12)
    ema26  = _ema(closes, 26)
    macd   = [a - b for a, b in zip(ema12, ema26)]
    sig    = _ema(macd, 9)
    hist   = [m - s for m, s in zip(macd, sig)]

    rsi_series = []
    for i in range(len(closes)):
        if i < 15:
            continue
        rsi_series.append({"time": dates[i], "value": round(_rsi(closes[:i+1]), 2)})

    return {
        "symbol":     sym,
        "name":       sym,
        "price":      round(closes[-1], 2),
        "candles":    [{"time": d, "open": o, "high": h, "low": l, "close": c}
                       for d, o, h, l, c, v in rows],
        "volumes":    [{"time": d, "value": v,
                        "color": "#00e15f55" if c >= o else "#ff373755"}
                       for d, o, h, l, c, v in rows],
        "ema20":      [{"time": d, "value": round(v, 2)} for d, v in zip(dates, ema20v)],
        "ema50":      [{"time": d, "value": round(v, 2)} for d, v in zip(dates, ema50v)],
        "macd":       [{"time": d, "value": round(v, 4)} for d, v in zip(dates, macd)],
        "signal":     [{"time": d, "value": round(v, 4)} for d, v in zip(dates, sig)],
        "hist":       [{"time": d, "value": round(v, 4),
                        "color": "#00e15f" if v >= 0 else "#ff3737"}
                       for d, v in zip(dates, hist)],
        "rsi":        rsi_series,
        "macd_val":   round(macd[-1], 4),
        "signal_val": round(sig[-1], 4),
        "hist_val":   round(hist[-1], 4),
        "rsi_val":    round(_rsi(closes), 1),
        "crossover":  macd[-1] > sig[-1],
    }


# ── Congressional Trading Data ───────────────────────────────────────────────────
HOUSE_PTR_SEARCH  = "https://disclosures-clerk.house.gov/FinancialDisclosure/ViewMemberSearchResult"
HOUSE_PTR_BASE    = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs"
SENATE_EFD_SEARCH = "https://efts.senate.gov/LATEST/search-index"
SENATE_EFD_DOC    = "https://efts.senate.gov/LATEST/search-index/{fid}/document"

_AMOUNT_RANK = {
    "$1,001 - $15,000": 1,      "$15,001 - $50,000": 2,
    "$50,001 - $100,000": 3,    "$100,001 - $250,000": 4,
    "$250,001 - $500,000": 5,   "$500,001 - $1,000,000": 6,
    "$1,000,001 - $5,000,000": 7, "over $5,000,000": 8,
}

_congress_cache  = {"data": [], "fetched": 0.0, "loading": False}
CONGRESS_TTL     = 86400  # re-fetch once per day (PDFs don't change)

_HDR_PAT   = re.compile(r"^(ID Owner|Cap\.|Gains|Notification|\$200|Amount Cap)")
_OWNER_PAT = re.compile(r"^(?:SP|JT|DC|SE|DEP|OC|OP)\s+")


def _search_house_ptrs(year):
    """Return list of (doc_id, member_name) from the House PTR search form."""
    try:
        r = requests.post(
            HOUSE_PTR_SEARCH,
            data={"LastName": "", "FilingYear": str(year), "State": "", "District": "", "FilingType": "P"},
            headers=HEADERS, timeout=30,
        )
        r.raise_for_status()
        pairs = re.findall(
            r'href="public_disc/ptr-pdfs/\d+/(\d+)\.pdf"[^>]*>([^<]+)</a>',
            r.text,
        )
        return [(doc_id, name.strip()) for doc_id, name in pairs]
    except Exception:
        return []


def _parse_ptr_pdf(doc_id, year):
    """Download one PTR PDF and return list of stock trade dicts."""
    try:
        url = f"{HOUSE_PTR_BASE}/{year}/{doc_id}.pdf"
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        reader = PdfReader(io.BytesIO(r.content))
        text = " ".join(p.extract_text() or "" for p in reader.pages).replace("\x00", "")

        name_m = re.search(r"Name\s*:\s*((?:Hon\.\s+)?[^\n]+)", text)
        name = name_m.group(1).strip() if name_m else "Unknown"

        tx_start = text.find("ID Owner Asset")
        if tx_start == -1:
            return []
        tx_text = text[tx_start:]
        cert = tx_text.find("I CERTIFY")
        if cert > -1:
            tx_text = tx_text[:cert]

        trades = []
        for m in re.finditer(
            r"\(([A-Z]{1,6})\)\s*\[ST\]\s*\n?\s*([PS])\s*"
            r"(\d{2}/\d{2}/\d{4})\d{2}/\d{2}/\d{4}"
            r"(\$[\d,]+\s*-\s*\n?\s*\$[\d,]+)",
            tx_text,
        ):
            ticker   = m.group(1)
            tx_type  = "PURCHASE" if m.group(2) == "P" else "SALE"
            tx_date  = m.group(3)          # MM/DD/YYYY
            amount   = re.sub(r"\s+", " ", m.group(4).strip())

            # Company name: look back up to 200 chars before (TICKER)
            snippet  = tx_text[max(0, m.start() - 200): m.start()]
            lines    = [l.strip() for l in snippet.split("\n")]
            parts    = []
            for line in reversed(lines):
                if not line:
                    continue
                if _HDR_PAT.match(line):
                    break
                line = _OWNER_PAT.sub("", line).strip()
                if line:
                    parts.insert(0, line)
                if len(parts) >= 3:
                    break
            company = " ".join(parts)[:48].strip()

            # Normalise date to YYYY-MM-DD
            try:
                iso_date = datetime.strptime(tx_date, "%m/%d/%Y").strftime("%Y-%m-%d")
            except ValueError:
                iso_date = tx_date

            trades.append({
                "chamber":          "HOUSE",
                "name":             name,
                "ticker":           ticker,
                "company":          company,
                "trade_type":       tx_type,
                "amount":           amount,
                "amount_rank":      _AMOUNT_RANK.get(amount, 0),
                "transaction_date": iso_date,
                "disclosure_date":  "",
                "source_url":       f"{HOUSE_PTR_BASE}/{year}/{doc_id}.pdf",
            })
        return trades
    except Exception:
        return []


def _fetch_congress_trades():
    """Scrape House PTR PDFs in parallel. Returns sorted list of trade dicts."""
    year  = datetime.now().year
    # (doc_id, filing_year) pairs
    tagged = [(doc_id, year) for doc_id, _ in _search_house_ptrs(year)]
    # Also pull prior year if we're early in the year (< April)
    if datetime.now().month < 4:
        tagged += [(doc_id, year - 1) for doc_id, _ in _search_house_ptrs(year - 1)]

    rows = []
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_parse_ptr_pdf, doc_id, yr): doc_id for doc_id, yr in tagged}
            for fut in as_completed(futures):
                rows.extend(fut.result())
    except RuntimeError:
        pass  # interpreter shutting down — ignore

    rows.sort(key=lambda x: x["transaction_date"], reverse=True)
    return rows


def _fetch_senate_trades():
    """Fetch Senate PTRs from eFD public API. Returns list of trade dicts."""
    year  = datetime.now().year
    years = [year, year - 1] if datetime.now().month < 4 else [year]
    rows  = []
    for yr in years:
        page = 1
        while True:
            try:
                r = requests.get(
                    SENATE_EFD_SEARCH,
                    params={
                        "q":          '""',
                        "dateFrom":   f"{yr}-01-01",
                        "dateTo":     f"{yr}-12-31",
                        "transactionType": "ST",
                        "pageSize":   200,
                        "page":       page,
                    },
                    headers=HEADERS, timeout=30,
                )
                r.raise_for_status()
                data = r.json()
                hits = data.get("hits", {}).get("hits", [])
                if not hits:
                    break
                for h in hits:
                    s   = h.get("_source", {})
                    fid = h.get("_id", "")
                    fname = (s.get("first_name") or "").strip()
                    lname = (s.get("last_name")  or "").strip()
                    name  = f"{fname} {lname}".strip() or "Unknown"
                    ticker  = (s.get("ticker")           or "").upper().strip()
                    company = (s.get("asset_name")       or "")[:48].strip()
                    raw_type = (s.get("transaction_type") or "").upper()
                    tx_type  = "PURCHASE" if "PURCH" in raw_type or raw_type == "P" else "SALE" if "SALE" in raw_type or raw_type == "S" else raw_type
                    amount   = (s.get("amount") or "").strip()
                    tx_date  = (s.get("transaction_date") or s.get("document_date") or "")[:10]
                    if not ticker or not tx_date:
                        continue
                    rows.append({
                        "chamber":          "SENATE",
                        "name":             name,
                        "ticker":           ticker,
                        "company":          company,
                        "trade_type":       tx_type,
                        "amount":           amount,
                        "amount_rank":      _AMOUNT_RANK.get(amount, 0),
                        "transaction_date": tx_date,
                        "disclosure_date":  (s.get("document_date") or "")[:10],
                        "source_url":       SENATE_EFD_DOC.format(fid=fid) if fid else "",
                    })
                total = data.get("hits", {}).get("total", {}).get("value", 0)
                if page * 200 >= total:
                    break
                page += 1
            except Exception:
                break
    return rows


def _bg_congress():
    """Background worker: fetch House + Senate trades and populate cache."""
    if _congress_cache["loading"]:
        return
    _congress_cache["loading"] = True
    try:
        house  = _fetch_congress_trades()
        senate = _fetch_senate_trades()
        combined = house + senate
        combined.sort(key=lambda x: x["transaction_date"], reverse=True)
        _congress_cache["data"]    = combined
        _congress_cache["fetched"] = time.time()
    finally:
        _congress_cache["loading"] = False


def _get_congress(force=False):
    now = time.time()
    stale = force or now - _congress_cache["fetched"] > CONGRESS_TTL or not _congress_cache["data"]
    if stale and not _congress_cache["loading"]:
        threading.Thread(target=_bg_congress, daemon=True).start()
    return _congress_cache["data"]  # return whatever is cached right now


# ── Legislation Data ─────────────────────────────────────────────────────────────
GOVTRACK_URL  = "https://www.govtrack.us/api/v2/bill"
LEGIS_TTL     = 3600   # 1-hour cache

_legis_cache  = {"data": [], "fetched": 0.0, "loading": False}


def _parse_bill_chambers(bill):
    """Return (house_passed, senate_passed, signed) from major_actions."""
    house_passed = senate_passed = False
    signed = bill.get("current_status") == "enacted_signed"
    for action in bill.get("major_actions", []):
        if len(action) < 4:
            continue
        xml = action[3]
        if 'where="h"' in xml and 'result="pass"' in xml:
            house_passed = True
        if 'where="s"' in xml and 'result="pass"' in xml:
            senate_passed = True
    return house_passed, senate_passed, signed


def _fetch_bills():
    """Fetch recent bills from GovTrack for the current Congress."""
    congress = 119
    bills    = []
    seen     = set()

    # Pull the most recently active bills across all statuses
    for offset in range(0, 600, 100):
        try:
            r = requests.get(
                GOVTRACK_URL,
                params={
                    "congress":   congress,
                    "order_by":   "-current_status_date",
                    "limit":      100,
                    "offset":     offset,
                },
                headers=HEADERS, timeout=15,
            )
            r.raise_for_status()
            for b in r.json().get("objects", []):
                bid = b.get("id") or b.get("display_number")
                if bid in seen:
                    continue
                seen.add(bid)
                sponsor      = b.get("sponsor") or {}
                sponsor_role = b.get("sponsor_role") or {}
                party        = sponsor_role.get("party", "")
                party_short  = {"Republican": "R", "Democrat": "D",
                                "Independent": "I"}.get(party, party[:1] if party else "?")
                hp, sp, sg   = _parse_bill_chambers(b)
                bills.append({
                    "bill_number":    b.get("display_number", ""),
                    "title":          (b.get("title_without_number") or b.get("title") or "")[:90],
                    "sponsor":        sponsor.get("name", "N/A"),
                    "party":          party_short,
                    "introduced":     b.get("introduced_date", ""),
                    "status_date":    b.get("current_status_date", ""),
                    "status":         b.get("current_status", ""),
                    "status_label":   b.get("current_status_label", ""),
                    "house_passed":   hp,
                    "senate_passed":  sp,
                    "signed":         sg,
                    "link":           b.get("link", ""),
                    "bill_type":      b.get("bill_type", ""),
                })
        except Exception:
            break

    return bills


def _bg_bills():
    if _legis_cache["loading"]:
        return
    _legis_cache["loading"] = True
    try:
        _legis_cache["data"]    = _fetch_bills()
        _legis_cache["fetched"] = time.time()
    finally:
        _legis_cache["loading"] = False


def _get_bills(force=False):
    now   = time.time()
    stale = force or now - _legis_cache["fetched"] > LEGIS_TTL or not _legis_cache["data"]
    if stale and not _legis_cache["loading"]:
        threading.Thread(target=_bg_bills, daemon=True).start()
    return _legis_cache["data"]


# ── JSON helper ──────────────────────────────────────────────────────────────────
class _NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer): return int(obj)
        if isinstance(obj, np.floating): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        return super().default(obj)


def _json(data):
    return Response(
        content=json.dumps(data, cls=_NumpyEncoder),
        media_type="application/json",
    )

# ── Launchpad / Home Data ────────────────────────────────────────────────────────
_home_cache = {"data": {}, "fetched": 0.0}
_news_cache = {"data": [], "fetched": 0.0}
HOME_TTL    = 300   # 5 min
NEWS_TTL    = 300


def _fetch_quote(symbol):
    """Fetch last-close price + daily change via Polygon aggregates.
    Using daily bars (last 2 trading days) works correctly whether the
    market is open, closed, or it's a weekend — no snapshot zeros."""
    today     = date.today()
    from_date = str(today - timedelta(days=10))  # 10 cal days → at least 2 trading days
    to_date   = str(today)
    extra = {} if symbol.startswith(("X:", "C:")) else {"adjusted": "true"}
    raw   = _poly_get(
        f"{POLYGON_BASE}/v2/aggs/ticker/{symbol}/range/1/day/{from_date}/{to_date}",
        params={"sort": "asc", "limit": 10, **extra},
    )
    bars  = [b for b in (raw.get("results") or []) if b.get("c") is not None]
    if not bars:
        return 0.0, 0.0, 0.0
    price = float(bars[-1]["c"])
    prev  = float(bars[-2]["c"]) if len(bars) >= 2 else price
    chg   = price - prev
    pct   = (chg / prev * 100) if prev else 0.0
    return round(price, 4), round(chg, 4), round(pct, 3)


def _fetch_home_data():
    sectors = []
    # Only fetch entries that have a real symbol (skip section headers where sym=None)
    fetchable = [(sym, name) for sym, name in LAUNCHPAD_INDICES if sym is not None]
    fetched   = {}
    with ThreadPoolExecutor(max_workers=20) as pool:
        idx_futs = {pool.submit(_fetch_quote, sym): (sym, name) for sym, name in fetchable}
        sec_futs = {pool.submit(_fetch_quote, sym): (sym, name) for sym, name in SECTORS}
        for fut, (sym, name) in idx_futs.items():
            try:
                price, chg, pct = fut.result()
                fetched[sym] = {"symbol": sym, "name": name, "price": price, "chg": chg, "pct": pct}
            except Exception:
                fetched[sym] = {"symbol": sym, "name": name, "price": 0, "chg": 0, "pct": 0}
        for fut, (sym, name) in sec_futs.items():
            try:
                price, chg, pct = fut.result()
                sectors.append({"symbol": sym, "name": name, "price": price, "chg": chg, "pct": pct})
            except Exception:
                sectors.append({"symbol": sym, "name": name, "price": 0, "chg": 0, "pct": 0})
    # Rebuild indices list in defined order, inserting section headers
    indices = []
    for sym, name in LAUNCHPAD_INDICES:
        if sym is None:
            indices.append({"symbol": None, "name": name, "header": True})
        elif sym in fetched:
            indices.append(fetched[sym])
    sec_order = {sym: i for i, (sym, _) in enumerate(SECTORS)}
    sectors.sort(key=lambda x: sec_order.get(x["symbol"], 99))
    # Top signals from screener
    all_stocks  = list(_state["stocks"].values())
    top_signals = sorted(
        [s for s in all_stocks if s["signal"] in ("BUY", "WATCH")],
        key=lambda x: x["total"], reverse=True,
    )[:12]
    return {"indices": indices, "sectors": sectors, "signals": top_signals}


def _get_home(force=False):
    now = time.time()
    if force or now - _home_cache["fetched"] > HOME_TTL or not _home_cache["data"]:
        try:
            _home_cache["data"]   = _fetch_home_data()
            _home_cache["fetched"] = now
        except Exception:
            pass
    return _home_cache["data"]


def _fetch_news():
    r = requests.get(
        f"{POLYGON_BASE}/v2/reference/news",
        params={"apiKey": POLYGON_API_KEY, "limit": 25, "order": "desc", "sort": "published_utc"},
        headers=HEADERS, timeout=10,
    )
    r.raise_for_status()
    news = []
    for item in r.json().get("results", []):
        title = (item.get("title") or "")[:110]
        link  = item.get("article_url") or "#"
        raw   = item.get("published_utc", "")
        try:
            ts = datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S").strftime("%H:%M")
        except Exception:
            ts = raw[11:16] if len(raw) >= 16 else ""
        if title:
            news.append({"title": title, "link": link, "time": ts})
    return news


def _get_news(force=False):
    now = time.time()
    if force or now - _news_cache["fetched"] > NEWS_TTL or not _news_cache["data"]:
        try:
            _news_cache["data"]    = _fetch_news()
            _news_cache["fetched"] = now
        except Exception:
            pass
    return _news_cache["data"]


# ── FastAPI ──────────────────────────────────────────────────────────────────────
app = FastAPI()


@app.get("/api/status")
async def api_status():
    loading = _state["loading"]
    loaded  = _state["loaded"]
    total   = _state["total"]
    pct     = loaded / total * 100 if total else 0
    filled  = int(pct / 5)
    n_buy   = sum(1 for s in _state["stocks"].values() if s["signal"] == "BUY")
    n_watch = sum(1 for s in _state["stocks"].values() if s["signal"] == "WATCH")
    n_no    = sum(1 for s in _state["stocks"].values() if s["signal"] == "NO BUY")
    nr      = max(0.0, _state["next_refresh"] - time.time())
    now_et = _et_now()
    return _json({
        "loading":      loading,
        "loaded":       loaded,
        "total":        total,
        "pct":          round(pct, 1),
        "bar":          "\u2588" * filled + "\u2591" * (20 - filled),
        "last_updated": _state["last_updated"],
        "next_refresh": round(nr),
        "error_count":  _state["error_count"],
        "n_buy":        n_buy,
        "n_watch":      n_watch,
        "n_no_buy":     n_no,
        "market_open":  _market_open(),
        "et_time":      now_et.strftime("%H:%M ET %a"),
    })


@app.get("/api/stocks")
async def api_stocks(
    index:  str = Query("ALL"),
    signal: str = Query("ALL"),
    sort:   str = Query("score"),
    dir:    str = Query("desc"),
    q:      str = Query(""),
):
    stocks = list(_state["stocks"].values())
    if index  != "ALL": stocks = [s for s in stocks if s["index"]  == index]
    if signal != "ALL": stocks = [s for s in stocks if s["signal"] == signal]
    if q:
        qu = q.upper()
        stocks = [s for s in stocks if qu in s["symbol"] or qu in s["name"].upper()]
    rev = (dir == "desc")
    if   sort == "ticker": stocks.sort(key=lambda s: s["symbol"], reverse=rev)
    elif sort == "price":  stocks.sort(key=lambda s: s["price"],  reverse=rev)
    else:                  stocks.sort(key=lambda s: s["total"],  reverse=rev)
    return _json({"stocks": stocks, "total_loaded": len(_state["stocks"])})


@app.post("/api/refresh")
async def api_refresh():
    already = _state["loading"]
    if not already:
        threading.Thread(target=_bg_refresh, daemon=True).start()
    return _json({"ok": True, "already_loading": already})


@app.get("/api/chart/{symbol}")
async def api_chart(symbol: str):
    try:
        data = _compute_chart_data(symbol.upper())
        if data is None:
            return _json({"error": "Not enough data"})
        return _json(data)
    except Exception as e:
        return _json({"error": str(e)})


@app.get("/chart/{symbol}", response_class=HTMLResponse)
async def chart_page(symbol: str):
    return CHART_HTML


@app.get("/api/portfolios")
async def api_portfolios(
    chamber: str = Query("ALL"),
    ttype:   str = Query("ALL"),
    sort:    str = Query("date"),
    dir:     str = Query("desc"),
    q:       str = Query(""),
):
    rows = _get_congress()
    if chamber != "ALL": rows = [r for r in rows if r["chamber"] == chamber]
    if ttype   != "ALL": rows = [r for r in rows if ttype in r["trade_type"]]
    if q:
        qu = q.upper()
        rows = [r for r in rows if qu in r["ticker"]
                                or qu in r["name"].upper()
                                or qu in r["company"].upper()]
    rev = (dir == "desc")
    if   sort == "amount": rows = sorted(rows, key=lambda r: r["amount_rank"],      reverse=rev)
    elif sort == "name":   rows = sorted(rows, key=lambda r: r["name"],             reverse=rev)
    elif sort == "ticker": rows = sorted(rows, key=lambda r: r["ticker"],           reverse=rev)
    else:                  rows = sorted(rows, key=lambda r: r["transaction_date"], reverse=rev)
    return _json({"trades": rows[:1000], "total": len(rows), "loading": _congress_cache["loading"]})


@app.post("/api/portfolios/refresh")
async def api_portfolios_refresh():
    threading.Thread(target=_get_congress, kwargs={"force": True}, daemon=True).start()
    return _json({"ok": True})


@app.get("/portfolios", response_class=HTMLResponse)
async def portfolios_page():
    return PORTFOLIOS_HTML


@app.get("/api/legis")
async def api_legis(
    chamber: str = Query("ALL"),
    status:  str = Query("ALL"),
    sort:    str = Query("date"),
    dir:     str = Query("desc"),
    q:       str = Query(""),
):
    rows = _get_bills()
    if chamber == "HOUSE":
        rows = [r for r in rows if r["bill_type"] in
                ("house_bill","house_joint_resolution","house_concurrent_resolution","house_resolution")]
    elif chamber == "SENATE":
        rows = [r for r in rows if r["bill_type"] in
                ("senate_bill","senate_joint_resolution","senate_concurrent_resolution","senate_resolution")]
    if status == "SIGNED":
        rows = [r for r in rows if r["signed"]]
    elif status == "PASSED":
        rows = [r for r in rows if r["house_passed"] and r["senate_passed"] and not r["signed"]]
    elif status == "PROGRESS":
        rows = [r for r in rows if (r["house_passed"] or r["senate_passed"]) and not (r["house_passed"] and r["senate_passed"])]
    elif status == "INTRODUCED":
        rows = [r for r in rows if not r["house_passed"] and not r["senate_passed"] and not r["signed"]]
    if q:
        qu = q.upper()
        rows = [r for r in rows if qu in r["bill_number"].upper()
                                or qu in r["title"].upper()
                                or qu in r["sponsor"].upper()]
    rev = (dir == "desc")
    if   sort == "bill":    rows = sorted(rows, key=lambda r: r["bill_number"],  reverse=rev)
    elif sort == "sponsor": rows = sorted(rows, key=lambda r: r["sponsor"],      reverse=rev)
    else:                   rows = sorted(rows, key=lambda r: r["status_date"],  reverse=rev)
    return _json({"bills": rows[:2000], "total": len(rows), "loading": _legis_cache["loading"]})


@app.post("/api/legis/refresh")
async def api_legis_refresh():
    threading.Thread(target=_get_bills, kwargs={"force": True}, daemon=True).start()
    return _json({"ok": True})


@app.get("/legis", response_class=HTMLResponse)
async def legis_page():
    return LEGIS_HTML


@app.get("/api/home")
async def api_home():
    d = dict(_get_home() or {})
    d["market_open"] = _market_open()
    d["et_time"]     = _et_now().strftime("%H:%M ET %a")
    return _json(d)


# ── Sector range fetch ────────────────────────────────────────────────────────────
def _sector_date_range(range_str):
    today = date.today()
    if range_str == "1w":  return str(today - timedelta(days=7)),   str(today)
    if range_str == "1m":  return str(today - timedelta(days=30)),  str(today)
    if range_str == "3m":  return str(today - timedelta(days=90)),  str(today)
    if range_str == "6m":  return str(today - timedelta(days=180)), str(today)
    if range_str == "ytd": return str(today.replace(month=1, day=1)), str(today)
    if range_str == "1y":  return str(today - timedelta(days=365)), str(today)
    return None, None  # 1d → use snapshot

def _fetch_sector_pct(symbol, range_str):
    if range_str == "1d":
        today = date.today()
        raw   = _poly_get(
            f"{POLYGON_BASE}/v2/aggs/ticker/{symbol}/range/1/day"
            f"/{today - timedelta(days=10)}/{today}",
            params={"adjusted": "true", "sort": "asc", "limit": 10},
        )
        bars  = [b["c"] for b in (raw.get("results") or []) if b.get("c") is not None]
        price = bars[-1] if bars else 0.0
        prev  = bars[-2] if len(bars) >= 2 else price
        pct   = (price - prev) / prev * 100 if prev else 0.0
    else:
        from_date, to_date = _sector_date_range(range_str)
        raw    = _poly_get(
            f"{POLYGON_BASE}/v2/aggs/ticker/{symbol}/range/1/day/{from_date}/{to_date}",
            params={"adjusted": "true", "sort": "asc", "limit": 500},
        )
        closes = [b["c"] for b in (raw.get("results") or []) if b.get("c") is not None]
        pct    = (closes[-1] - closes[0]) / closes[0] * 100 if len(closes) >= 2 else 0.0
    return round(pct, 3)


def _fetch_sectors_for_range(range_str):
    results = []
    with ThreadPoolExecutor(max_workers=11) as pool:
        futs = {pool.submit(_fetch_sector_pct, sym, range_str): (sym, name) for sym, name in SECTORS}
        for fut, (sym, name) in futs.items():
            try:
                pct = fut.result()
            except Exception:
                pct = 0.0
            results.append({"symbol": sym, "name": name, "pct": pct})
    order = {sym: i for i, (sym, _) in enumerate(SECTORS)}
    results.sort(key=lambda x: order.get(x["symbol"], 99))
    return results


@app.get("/api/sectors")
async def api_sectors(range: str = "1d"):
    return _json({"sectors": _fetch_sectors_for_range(range)})


@app.get("/api/news")
async def api_news():
    return _json({"items": _get_news()})


@app.get("/screener", response_class=HTMLResponse)
async def screener_page():
    return HTML_PAGE


# ── Launchpad page ───────────────────────────────────────────────────────────────
LAUNCHPAD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vinny's Intelligence Terminal</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{
  --bg:#02020c;--bg2:#040614;--bg3:#060818;
  --hdr:#000212;--amber:#ffa000;--abright:#ffd23c;--adim:#825200;
  --white:#e1e1ee;--muted:#4e536c;--green:#00e15f;--red:#ff3737;
  --cyan:#37c3ff;--border:#162a50;--panel:#030510;
  --btn:#0a193c;--btnhov:#142d64;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{background:var(--bg);color:var(--white);
  font-family:Consolas,'Lucida Console','Courier New',monospace;
  font-size:16px;display:flex;flex-direction:column;padding:8px 10px}
.nav{display:flex;gap:0;margin-bottom:5px;border-bottom:1px solid var(--border);flex-shrink:0}
.nav a{color:var(--muted);text-decoration:none;padding:4px 14px;font-size:14px;
  letter-spacing:.6px;border-bottom:2px solid transparent;margin-bottom:-1px}
.nav a:hover{color:var(--amber)}
.nav a.active{color:var(--abright);border-bottom-color:var(--abright)}
.top-bar{display:flex;align-items:baseline;gap:16px;margin-bottom:5px;flex-shrink:0}
.brand{color:var(--abright);font-size:21px;font-weight:bold;letter-spacing:1px}
.tagline{color:var(--adim);font-size:14px}
.clock{margin-left:auto;color:var(--muted);font-size:15px}
.grid{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:2fr 1fr;
  gap:8px;flex:1;min-height:0}
.panel{background:var(--panel);border:1px solid var(--border);
  display:flex;flex-direction:column;overflow:hidden}
.panel-hdr{background:var(--hdr);padding:6px 10px;font-size:14px;letter-spacing:.8px;
  color:var(--adim);border-bottom:1px solid var(--border);flex-shrink:0;
  display:flex;align-items:center;gap:8px}
.panel-hdr .dot{color:var(--abright);font-size:16px}
.panel-hdr .sub{margin-left:auto;color:var(--muted);font-size:12px}
.panel-body{flex:1;overflow:auto;padding:0}
/* Market Monitor */
.idx-table{width:100%;border-collapse:collapse}
.idx-table td{padding:4px 10px;border-bottom:1px solid #0a1428;white-space:nowrap}
.idx-table tr:hover td{background:#071230}
.idx-name{color:var(--muted);width:130px;font-size:14px;letter-spacing:.3px}
.idx-price{color:var(--white);text-align:right;width:110px;font-size:15px}
.idx-chg{text-align:right;width:90px;font-size:14px}
.idx-pct{text-align:right;width:80px;font-size:15px;font-weight:bold}
.pos{color:var(--green)}.neg{color:var(--red)}.flat{color:var(--muted)}
/* Sector chart */
.chart-wrap{flex:1;padding:8px;display:flex;align-items:stretch;justify-content:center;min-height:0;position:relative}
canvas{width:100%!important;height:100%!important}
.tf-btn{background:#0d1830;border:1px solid #1e2d50;color:#a0a8c0;font-family:Consolas,'Courier New',monospace;font-size:12px;padding:2px 8px;cursor:pointer;border-radius:2px}
.tf-btn:hover{background:#1a2840;color:#fff}
.tf-btn.active{background:#1a3a6e;border-color:#3a6bbf;color:#f0b429;font-weight:bold}
/* Top Signals */
.sig-table{width:100%;border-collapse:collapse}
.sig-table td{padding:4px 8px;border-bottom:1px solid #0a1428;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sig-table tr:hover td{background:#071230}
.sig-ticker{color:var(--abright);width:62px;font-weight:bold}
.sig-name{color:var(--white);max-width:160px;overflow:hidden;text-overflow:ellipsis}
.sig-score{text-align:right;color:var(--cyan);width:44px}
.sig-rsi{text-align:right;color:var(--muted);width:46px;font-size:14px}
.sig-buy{color:var(--green);font-size:14px;text-align:center;width:58px;font-weight:bold}
.sig-watch{color:var(--amber);font-size:14px;text-align:center;width:58px}
/* News */
.news-list{padding:2px 0}
.news-item{padding:5px 10px;border-bottom:1px solid #0a1428;cursor:pointer}
.news-item:hover{background:#071230}
.news-time{color:var(--adim);font-size:13px;margin-bottom:2px}
.news-title{color:var(--white);font-size:14px;line-height:1.4;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.news-item a{color:inherit;text-decoration:none}
.news-item a:hover .news-title{color:var(--abright)}
/* Loading */
.loading{color:var(--adim);padding:20px 10px;font-size:14px}
</style>
</head>
<body>
<div class="nav">
  <a href="/" class="active">LAUNCHPAD</a>
  <a href="/screener">SCREENER</a>
  <a href="/portfolios">PORTFOLIOS</a>
  <a href="/legis">LEGIS</a>
</div>
<div class="top-bar">
  <span class="brand">&#9672; VINNY'S INTELLIGENCE TERMINAL</span>
  <span class="tagline">MARKET LAUNCHPAD</span>
  <span class="clock" id="clock"></span>
</div>

<div class="grid">

  <!-- Panel 1: Market Monitor -->
  <div class="panel">
    <div class="panel-hdr">
      <span class="dot">&#9672;</span> MARKET MONITOR
      <span class="sub" id="mkt-updated"></span>
    </div>
    <div id="lp-market-banner" style="display:none;background:#1a0a00;border-bottom:1px solid #f0b429;color:#f0b429;font-size:11px;padding:3px 8px;letter-spacing:.5px;">
      &#9632; MARKET CLOSED &mdash; <span id="lp-banner-time"></span> &mdash; Last closing prices
    </div>
    <div class="panel-body" id="mkt-body">
      <div class="loading">&nbsp; Loading market data...</div>
    </div>
  </div>

  <!-- Panel 2: Sector Performance -->
  <div class="panel">
    <div class="panel-hdr">
      <span class="dot">&#9672;</span> <span id="sec-title">SECTOR PERFORMANCE &mdash; TODAY</span>
      <span class="sub" id="sec-updated"></span>
    </div>
    <div style="display:flex;gap:4px;padding:4px 8px;background:var(--panel)">
      <button class="tf-btn active" onclick="setSectorRange('1d',this)">1D</button>
      <button class="tf-btn" onclick="setSectorRange('1w',this)">1W</button>
      <button class="tf-btn" onclick="setSectorRange('1m',this)">1M</button>
      <button class="tf-btn" onclick="setSectorRange('3m',this)">3M</button>
      <button class="tf-btn" onclick="setSectorRange('6m',this)">6M</button>
      <button class="tf-btn" onclick="setSectorRange('ytd',this)">YTD</button>
      <button class="tf-btn" onclick="setSectorRange('1y',this)">1Y</button>
    </div>
    <div class="chart-wrap">
      <canvas id="sector-chart"></canvas>
    </div>
  </div>

  <!-- Panel 3: Top Signals -->
  <div class="panel">
    <div class="panel-hdr">
      <span class="dot">&#9672;</span> TOP SIGNALS
      <span class="sub">FROM SCREENER</span>
    </div>
    <div class="panel-body" id="sig-body">
      <div class="loading">&nbsp; Waiting for screener data...</div>
    </div>
  </div>

  <!-- Panel 4: Market News -->
  <div class="panel">
    <div class="panel-hdr">
      <span class="dot">&#9672;</span> MARKET NEWS
      <span class="sub" id="news-updated"></span>
    </div>
    <div class="panel-body" id="news-body">
      <div class="loading">&nbsp; Loading news feed...</div>
    </div>
  </div>

</div>

<script>
let sectorChart = null;

function tick(){document.getElementById('clock').textContent=new Date().toTimeString().slice(0,8);}
setInterval(tick,1000); tick();

function pctCls(v){return v>0?'pos':v<0?'neg':'flat';}
function sign(v){return v>0?'+':'';}
function fmtPrice(v,sym){
  if(sym==='X:BTCUSD'||v>10000) return v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
  if(v<1) return v.toFixed(4);
  return v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
}

async function loadHome(){
  try{
    const r=await fetch('/api/home');
    const d=await r.json();
    renderMarket(d.indices||[]);
    renderSectors(d.sectors||[]);
    renderSignals(d.signals||[]);
    const ts='Updated '+new Date().toTimeString().slice(0,8);
    document.getElementById('mkt-updated').textContent=ts;
    document.getElementById('sec-updated').textContent=ts;
    // Market closed banner
    const banner=document.getElementById('lp-market-banner');
    const bannerTime=document.getElementById('lp-banner-time');
    if(d.market_open===false){
      banner.style.display='block';
      bannerTime.textContent=d.et_time||'';
    } else {
      banner.style.display='none';
    }
  }catch(e){console.error(e);}
}

async function loadNews(){
  try{
    const r=await fetch('/api/news');
    const d=await r.json();
    renderNews(d.items||[]);
    document.getElementById('news-updated').textContent='Updated '+new Date().toTimeString().slice(0,8);
  }catch(e){}
}

function renderMarket(rows){
  if(!rows.length){document.getElementById('mkt-body').innerHTML='<div class="loading">&nbsp; No data.</div>';return;}
  document.getElementById('mkt-body').innerHTML=`
    <table class="idx-table">
      ${rows.map(r=>r.header?`<tr>
        <td colspan="4" style="color:#f0b429;font-size:11px;padding:4px 2px 2px 4px;letter-spacing:1px;opacity:0.8;">${r.name}</td>
      </tr>`:`<tr>
        <td class="idx-name">&nbsp;${r.name}</td>
        <td class="idx-price">${fmtPrice(r.price,r.symbol)}</td>
        <td class="idx-chg ${pctCls(r.chg)}">${sign(r.chg)}${r.chg.toFixed(2)}</td>
        <td class="idx-pct ${pctCls(r.pct)}">${sign(r.pct)}${r.pct.toFixed(2)}%</td>
      </tr>`).join('')}
    </table>`;
}

function renderSectors(sectors){
  if(!sectors.length) return;
  const labels = sectors.map(s=>s.name);
  const pcts   = sectors.map(s=>s.pct);
  const colors = pcts.map(p=>{
    if(p>=0){
      const g=Math.min(255,80+p*40);
      return `rgba(0,${g},70,0.88)`;
    } else {
      const r=Math.min(255,140+Math.abs(p)*30);
      return `rgba(${r},40,40,0.88)`;
    }
  });

  if(sectorChart) sectorChart.destroy();
  const ctx=document.getElementById('sector-chart').getContext('2d');
  sectorChart=new Chart(ctx,{
    type:'polarArea',
    data:{
      labels,
      datasets:[{
        data: pcts.map(p=>Math.max(Math.abs(p),0.4)),
        backgroundColor: colors,
        borderColor:'#0d1830',
        borderWidth:1,
      }]
    },
    options:{
      responsive:true,
      maintainAspectRatio:false,
      plugins:{
        legend:{
          position:'right',
          labels:{
            color:'#ffffff',
            font:{family:"Consolas,'Courier New',monospace",size:13},
            boxWidth:14,padding:10,
            generateLabels(chart){
              return chart.data.labels.map((label,i)=>{
                const pct=pcts[i];
                return{
                  text:`${label}  ${pct>=0?'+':''}${pct.toFixed(2)}%`,
                  fillStyle:colors[i],strokeStyle:'#0d1830',lineWidth:1,
                  hidden:false,index:i,fontColor:'#ffffff',color:'#ffffff'
                };
              });
            }
          }
        },
        tooltip:{
          callbacks:{label:(ctx)=>{
            const p=pcts[ctx.dataIndex];
            return ` ${ctx.label}: ${p>=0?'+':''}${p.toFixed(2)}%`;
          }}
        }
      },
      scales:{r:{
        ticks:{display:false},
        grid:{color:'#1a2840'},
        angleLines:{color:'#1a2840'},
      }}
    }
  });
}

const _SEC_LABELS={'1d':'TODAY','1w':'THIS WEEK','1m':'THIS MONTH','3m':'3 MONTHS','6m':'6 MONTHS','ytd':'YTD','1y':'1 YEAR'};
async function setSectorRange(range,btn){
  document.querySelectorAll('.tf-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('sec-title').textContent=`SECTOR PERFORMANCE \u2014 ${_SEC_LABELS[range]||range.toUpperCase()}`;
  document.getElementById('sec-updated').textContent='Loading...';
  try{
    const r=await fetch(`/api/sectors?range=${range}`);
    const d=await r.json();
    renderSectors(d.sectors||[]);
    document.getElementById('sec-updated').textContent='Updated '+new Date().toTimeString().slice(0,8);
  }catch(e){console.error(e);}
}

function renderSignals(sigs){
  if(!sigs.length){document.getElementById('sig-body').innerHTML='<div class="loading">&nbsp; Waiting for screener...</div>';return;}
  document.getElementById('sig-body').innerHTML=`
    <table class="sig-table">
      <thead><tr style="background:#000212">
        <th style="padding:4px 8px;color:#4e536c;font-weight:normal;font-size:13px">TICKER</th>
        <th style="padding:4px 8px;color:#4e536c;font-weight:normal;font-size:13px">COMPANY</th>
        <th style="padding:4px 8px;color:#4e536c;font-weight:normal;font-size:13px;text-align:right">SCORE</th>
        <th style="padding:4px 8px;color:#4e536c;font-weight:normal;font-size:13px;text-align:right">RSI</th>
        <th style="padding:4px 8px;color:#4e536c;font-weight:normal;font-size:13px;text-align:center">SIG</th>
      </tr></thead>
      <tbody>
      ${sigs.map(s=>`<tr onclick="window.open('/chart/${s.symbol}','_blank')" style="cursor:pointer">
        <td class="sig-ticker">&nbsp;${s.symbol}</td>
        <td class="sig-name">&nbsp;${(s.name||'').slice(0,22)}</td>
        <td class="sig-score">${s.total}</td>
        <td class="sig-rsi">${s.rsi}</td>
        <td class="${s.signal==='BUY'?'sig-buy':'sig-watch'}">${s.signal}</td>
      </tr>`).join('')}
      </tbody>
    </table>`;
}

function renderNews(items){
  if(!items.length){document.getElementById('news-body').innerHTML='<div class="loading">&nbsp; No news available.</div>';return;}
  document.getElementById('news-body').innerHTML=`<div class="news-list">
    ${items.map(n=>`<div class="news-item">
      <a href="${n.link}" target="_blank">
        <div class="news-time">&nbsp;${n.time}</div>
        <div class="news-title">&nbsp;${n.title}</div>
      </a>
    </div>`).join('')}
  </div>`;
}

// Initial load
loadHome();
loadNews();
// Refresh every 5 minutes
setInterval(loadHome, 300000);
setInterval(loadNews, 300000);
</script>
</body>
</html>"""


# ── HTML page ────────────────────────────────────────────────────────────────────
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vinny's Intelligence Terminal</title>
<style>
:root{
  --bg:#02020c;--bg-row:#04061414;--bg-alt:#080b1b;
  --hdr:#000212;--amber:#ffa000;--abright:#ffd23c;--adim:#825200;
  --white:#e1e1ee;--muted:#4e536c;--green:#00e15f;--red:#ff3737;
  --yellow:#ffd71e;--cyan:#37c3ff;--border:#162a50;
  --btn:#0a193c;--btnhov:#142d64;--btnact:#234696;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{
  background:var(--bg);color:var(--white);
  font-family:Consolas,'Lucida Console','Courier New',monospace;
  font-size:13px;padding:12px 14px;
  display:flex;flex-direction:column;gap:0;
}
/* ── Nav ── */
.nav{display:flex;gap:0;margin-bottom:6px;border-bottom:1px solid var(--border);flex-shrink:0}
.nav a{color:var(--muted);text-decoration:none;padding:4px 14px;font-size:12px;letter-spacing:.6px;border-bottom:2px solid transparent;margin-bottom:-1px}
.nav a:hover{color:var(--amber)}
.nav a.active{color:var(--abright);border-bottom-color:var(--abright)}
/* ── Header ── */
.hdr{display:flex;align-items:baseline;gap:20px;margin-bottom:3px}
.title{color:var(--abright);font-size:19px;font-weight:bold;letter-spacing:.5px}
.subtitle{color:var(--adim);font-size:12px}
.clock{color:var(--muted);margin-left:auto;font-size:12px}
.tagline{color:var(--adim);font-size:11px;margin-bottom:6px}
hr{border:none;border-top:1px solid var(--border);margin:5px 0}
/* ── Controls ── */
.controls{display:flex;align-items:center;flex-wrap:wrap;gap:3px;padding:5px 0}
.clabel{color:var(--muted);font-size:12px;margin:0 3px 0 8px}
.clabel:first-child{margin-left:0}
.sp{width:10px;display:inline-block}
button{
  background:var(--btn);color:var(--white);
  border:1px solid var(--border);padding:3px 9px;
  cursor:pointer;font-family:inherit;font-size:12px;height:24px;
  transition:background .1s;
}
button:hover{background:var(--btnhov)}
button.active{background:var(--btnact);border-color:var(--adim);color:var(--abright)}
#search{
  background:#080c20;color:var(--white);border:1px solid var(--border);
  padding:3px 8px;font-family:inherit;font-size:12px;width:140px;height:24px;
}
#search::placeholder{color:var(--muted)}
#search:focus{outline:1px solid var(--adim);outline-offset:0}
#lbl-status{color:var(--amber);font-size:12px;margin-left:8px}
/* ── Table wrapper ── */
.tbl-wrap{flex:1;overflow:auto;border:1px solid var(--border);min-height:0}
table{width:100%;border-collapse:collapse;table-layout:fixed}
thead tr{background:var(--hdr);position:sticky;top:0;z-index:5}
th{
  color:var(--adim);text-align:left;padding:6px 8px;
  border-right:1px solid var(--border);border-bottom:2px solid var(--border);
  font-weight:normal;white-space:nowrap;user-select:none;font-size:12px;
}
th.sortable{cursor:pointer}
th.sortable:hover{color:var(--amber)}
th.sort-active{color:var(--abright)}
td{padding:4px 8px;border-right:1px solid #0d1830;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:13px}
tbody tr:nth-child(odd){background:var(--bg-row)}
tbody tr:nth-child(even){background:var(--bg-alt)}
tbody tr:hover{background:#0d1535}
/* col widths */
.c0{width:46px}.c1{width:78px}.c2{width:230px}
.c3{width:96px;text-align:right}.c4,.c5,.c6,.c7,.c8{width:134px}
.c9{width:78px;text-align:right}.c10{width:90px}.c11{width:58px}
/* cell colours */
.tc{color:var(--abright)} .nc{color:var(--white)} .mc{color:var(--muted)}
.pc{color:var(--amber)}   .bc{color:var(--cyan)}
.buy{color:var(--green)}  .watch{color:var(--yellow)} .nobuy{color:var(--red)}
.sh{color:var(--green)}   .sm{color:var(--yellow)}    .sl{color:var(--red)}
.ic{color:var(--adim)}
/* ── Clickable MACD cell ── */
.ticker-cell{cursor:pointer}
.ticker-cell:hover{color:#ffffff !important;text-decoration:underline}
/* ── Status bar ── */
.sbar{display:flex;align-items:center;gap:20px;font-size:11px;padding:4px 0}
.sp2{color:var(--amber)}
#lbl-count{color:var(--adim)}
#lbl-updated{color:var(--muted)}
/* ── Loading overlay ── */
#loading-msg{
  display:flex;align-items:center;justify-content:center;
  min-height:200px;color:var(--amber);font-size:14px;letter-spacing:.5px;
}
/* ── Scrollbar ── */
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:#1e3258;border-radius:2px}
::-webkit-scrollbar-thumb:hover{background:#2d4a7a}
</style>
</head>
<body>

<div class="hdr">
  <div class="nav"><a href="/">LAUNCHPAD</a><a href="/screener" class="active">SCREENER</a><a href="/portfolios">PORTFOLIOS</a><a href="/legis">LEGIS</a></div>
  <span class="title">&#9672; MOWAD INTELLIGENCE TERMINAL</span>
  <span class="subtitle">MULTI-FACTOR STOCK SCORING ENGINE</span>
  <span class="clock" id="clock"></span>
</div>
<div class="tagline">&nbsp;&nbsp;EMA Momentum &middot; MACD &middot; RSI &middot; Linear Trend &middot; Analyst Ratings
  &nbsp;&nbsp;&#x2502;&nbsp;&nbsp; Universe: S&amp;P 500 &middot; NASDAQ 100 &middot; Dow Jones 30</div>
<hr>

<div class="controls">
  <span class="clabel">INDEX:</span>
  <button class="active" data-group="index" data-val="ALL"   onclick="setFilter(this)"> ALL </button>
  <button               data-group="index" data-val="DOW"   onclick="setFilter(this)"> DOW </button>
  <button               data-group="index" data-val="NDAQ"  onclick="setFilter(this)"> NASDAQ </button>
  <button               data-group="index" data-val="SP500" onclick="setFilter(this)"> S&amp;P500 </button>

  <span class="sp"></span>
  <span class="clabel">SIGNAL:</span>
  <button class="active" data-group="signal" data-val="ALL"    onclick="setFilter(this)"> ALL </button>
  <button               data-group="signal" data-val="BUY"    onclick="setFilter(this)"> BUY </button>
  <button               data-group="signal" data-val="WATCH"  onclick="setFilter(this)"> WATCH </button>
  <button               data-group="signal" data-val="NO BUY" onclick="setFilter(this)"> NO BUY </button>

  <span class="sp"></span>
  <span class="clabel">SORT:</span>
  <button data-sort="score"  onclick="setSort(this)"> SCORE </button>
  <button data-sort="ticker" onclick="setSort(this)"> TICKER </button>
  <button data-sort="price"  onclick="setSort(this)"> PRICE </button>

  <span class="sp"></span>
  <span class="clabel">SEARCH:</span>
  <input id="search" type="text" placeholder="ticker or name" oninput="debounceSearch()">

  <span class="sp"></span>
  <button onclick="manualRefresh()"> REFRESH </button>
  <span id="lbl-status"></span>
</div>
<hr>

<div id="market-banner" style="display:none;background:#1a0a00;border:1px solid #f0b429;color:#f0b429;font-size:13px;padding:5px 12px;margin-bottom:6px;letter-spacing:.6px;">
  &#9632; MARKET CLOSED &mdash; <span id="market-banner-time"></span> &mdash; Showing last closing prices
</div>
<div class="tbl-wrap" id="tbl-wrap">
  <div id="loading-msg">Initializing&hellip;</div>
  <table id="data-table" style="display:none">
    <thead><tr>
      <th class="c0">&nbsp;#</th>
      <th class="c1">TICKER</th>
      <th class="c2">COMPANY</th>
      <th class="c3 sortable sort-active" data-sort="price" onclick="thSort(this)">PRICE &#9660;</th>
      <th class="c4">EMA&nbsp;/20</th>
      <th class="c5">MACD /20</th>
      <th class="c6">RSI&nbsp;&nbsp;/20</th>
      <th class="c7">TREND/20</th>
      <th class="c8"><a href="https://www.tipranks.com" target="_blank" rel="noopener" style="color:inherit;text-decoration:none;" title="Analyst ratings via TipRanks">ANLYST/20 &#x1F517;</a></th>
      <th class="c9 sortable sort-active" id="th-score" data-sort="score" onclick="thSort(this)">SCORE &#9660;</th>
      <th class="c10">SIGNAL</th>
      <th class="c11">IDX</th>
    </tr></thead>
    <tbody id="tbody"></tbody>
  </table>
</div>
<hr>
<div class="sbar">
  <span id="lbl-progress" class="sp2"></span>
  <span id="lbl-count"></span>
  <span id="lbl-updated"></span>
  <span id="lbl-countdown" style="color:var(--muted);margin-left:auto"></span>
</div>

<script>
const S = {
  filterIndex:'ALL', filterSignal:'ALL',
  sortKey:'score', sortDir:'desc',
  search:'', polling:false,
  nextRefresh:0, cdTimer:null, pollTimer:null
};
let searchTimer = null;

// ── Clock ──────────────────────────────────────────────────────────────────────
function tick(){
  const n=new Date();
  document.getElementById('clock').textContent =
    n.toTimeString().slice(0,8);
}
setInterval(tick,1000); tick();

// ── Countdown ─────────────────────────────────────────────────────────────────
function startCountdown(sec){
  clearInterval(S.cdTimer);
  let rem = sec;
  const el = document.getElementById('lbl-countdown');
  const upd = ()=>{
    if(rem<=0){el.textContent='';return;}
    const m=Math.floor(rem/60), s=String(rem%60).padStart(2,'0');
    el.textContent=`  Next refresh in ${m}:${s}`;
    rem--;
  };
  upd();
  S.cdTimer = setInterval(upd,1000);
}

// ── Filter / Sort helpers ──────────────────────────────────────────────────────
function setFilter(btn){
  const grp=btn.dataset.group, val=btn.dataset.val;
  document.querySelectorAll(`[data-group="${grp}"]`).forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  if(grp==='index')  S.filterIndex=val;
  if(grp==='signal') S.filterSignal=val;
  fetchAndRender();
}

function setSort(btn){
  const key=btn.dataset.sort;
  if(S.sortKey===key) S.sortDir=(S.sortDir==='desc'?'asc':'desc');
  else{S.sortKey=key; S.sortDir='desc';}
  fetchAndRender();
}

function thSort(th){
  const key=th.dataset.sort;
  setSort({dataset:{sort:key}});
}

function debounceSearch(){
  clearTimeout(searchTimer);
  searchTimer=setTimeout(()=>{S.search=document.getElementById('search').value;fetchAndRender();},300);
}

// ── Fetch & render ─────────────────────────────────────────────────────────────
async function fetchAndRender(){
  const params=new URLSearchParams({
    index:S.filterIndex, signal:S.filterSignal,
    sort:S.sortKey, dir:S.sortDir, q:S.search
  });
  const r=await fetch('/api/stocks?'+params);
  const data=await r.json();
  renderTable(data.stocks, data.total_loaded);
}

function fmt(n){return n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});}

function renderTable(rows, totalLoaded){
  document.getElementById('loading-msg').style.display='none';
  document.getElementById('data-table').style.display='';
  document.getElementById('lbl-count').textContent=
    `  Showing ${rows.length} of ${totalLoaded} stocks`;

  const tbody=document.getElementById('tbody');
  if(!rows.length){
    tbody.innerHTML='<tr><td colspan="12" style="color:var(--muted);padding:20px 12px">  No stocks match the current filters.</td></tr>';
    return;
  }
  const sigCls=s=>s==='BUY'?'buy':s==='WATCH'?'watch':'nobuy';
  const scrCls=t=>t>=65?'sh':t>=40?'sm':'sl';

  tbody.innerHTML=rows.map((s,i)=>{
    const am=s.analyst_mean;
    const tipranks=`https://www.tipranks.com/stocks/${s.symbol.toLowerCase()}/analyst-ratings`;
    const aBars=am!=null?`${s.bar_analyst}&nbsp;${String(s.analyst_s).padStart(2)}/20`
                        :`${s.bar_analyst}&nbsp;&nbsp;<a href="${tipranks}" target="_blank" rel="noopener" title="View analyst ratings on TipRanks" style="color:var(--abright);text-decoration:none;">N/A &#x1F517;</a>`;
    return `<tr>
      <td class="c0 mc">&nbsp;${i+1}</td>
      <td class="c1 tc ticker-cell" onclick="openChart('${s.symbol}')" title="Click to open chart">&nbsp;${s.symbol}</td>
      <td class="c2 nc ticker-cell" onclick="openChart('${s.symbol}')" title="Click to open chart">&nbsp;${s.name}</td>
      <td class="c3 pc">$${fmt(s.price)}&nbsp;</td>
      <td class="c4 bc">${s.bar_ema}&nbsp;${String(s.ema_s).padStart(2)}/20</td>
      <td class="c5 bc">${s.bar_macd}&nbsp;${String(s.macd_s).padStart(2)}/20</td>
      <td class="c6 bc">${s.bar_rsi}&nbsp;${String(s.rsi_s).padStart(2)}/20</td>
      <td class="c7 bc">${s.bar_trend}&nbsp;${String(s.trend_s).padStart(2)}/20</td>
      <td class="c8 ${am!=null?'bc':'mc'}">${aBars}</td>
      <td class="c9 ${scrCls(s.total)}">&nbsp;${s.total}/100</td>
      <td class="c10 ${sigCls(s.signal)}">&nbsp;&#9670; ${s.signal}</td>
      <td class="c11 ic">&nbsp;${s.index}</td>
    </tr>`;
  }).join('');
}

// ── Status polling ─────────────────────────────────────────────────────────────
async function pollStatus(){
  try{
    const r=await fetch('/api/status');
    const st=await r.json();
    const lbl=document.getElementById('lbl-status');
    const prg=document.getElementById('lbl-progress');
    const upd=document.getElementById('lbl-updated');

    if(st.loading){
      prg.textContent=`  Loading  [${st.bar}]  ${st.loaded}/${st.total}`;
      lbl.textContent='  FETCHING...';
      lbl.style.color='var(--amber)';
      document.getElementById('loading-msg').textContent=
        `Loading  [${st.bar}]  ${st.loaded}/${st.total}`;
      S.pollTimer=setTimeout(pollStatus,500);
    } else {
      S.polling=false;
      prg.textContent='';
      lbl.textContent='  READY';
      lbl.style.color='var(--green)';
      upd.textContent=`  Updated: ${st.last_updated}`+
        `   |   BUY: ${st.n_buy}   WATCH: ${st.n_watch}   NO BUY: ${st.n_no_buy}`+
        `   |   Errors: ${st.error_count}`;
      // Market closed banner
      const banner=document.getElementById('market-banner');
      const bannerTime=document.getElementById('market-banner-time');
      if(st.market_open===false){
        banner.style.display='block';
        bannerTime.textContent=st.et_time||'';
      } else {
        banner.style.display='none';
      }
      startCountdown(st.next_refresh);
      await fetchAndRender();
      setTimeout(manualRefresh, st.next_refresh*1000);
    }
  } catch(e){
    S.pollTimer=setTimeout(pollStatus,2000);
  }
}

// ── Manual refresh ─────────────────────────────────────────────────────────────
function openChart(symbol){
  window.open('/chart/'+symbol,'chart_'+symbol,
    'width=1120,height=860,resizable=yes,scrollbars=no,menubar=no,toolbar=no');
}

async function manualRefresh(){
  clearInterval(S.cdTimer);
  document.getElementById('lbl-countdown').textContent='';
  await fetch('/api/refresh',{method:'POST'});
  if(!S.polling){S.polling=true; pollStatus();}
}

// ── Init ───────────────────────────────────────────────────────────────────────
manualRefresh();
</script>
</body>
</html>"""


# ── MACD Chart page ──────────────────────────────────────────────────────────────
CHART_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Chart</title>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
:root{
  --bg:#02020c;--amber:#ffa000;--abright:#ffd23c;--adim:#825200;
  --white:#e1e1ee;--muted:#4e536c;--green:#00e15f;--red:#ff3737;
  --yellow:#ffd71e;--cyan:#37c3ff;--border:#162a50;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden;background:var(--bg);color:var(--white);
  font-family:Consolas,'Lucida Console','Courier New',monospace;font-size:13px}
body{display:flex;flex-direction:column;padding:10px 14px}
.hdr{display:flex;align-items:baseline;gap:14px;margin-bottom:4px;flex-shrink:0}
.sym{color:var(--abright);font-size:20px;font-weight:bold}
.nm{color:var(--adim)}
.price{color:var(--amber);margin-left:auto;font-size:15px}
hr{border:none;border-top:1px solid var(--border);margin:4px 0;flex-shrink:0}
.stats{display:flex;gap:22px;padding:4px 2px;flex-shrink:0}
.stat-lbl{color:var(--muted);font-size:10px}
.stat-val{font-size:13px;font-weight:bold}
.pos{color:var(--green)}.neg{color:var(--red)}.neu{color:var(--yellow)}
/* chart panels */
.charts{flex:1;display:flex;flex-direction:column;gap:3px;min-height:0}
.cpanel{position:relative;background:#030510;border:1px solid var(--border)}
#pw{flex:0 0 52%}
#mw{flex:0 0 26%}
#rw{flex:1}
.clbl{position:absolute;top:5px;left:9px;font-size:10px;color:var(--muted);z-index:5;pointer-events:none;letter-spacing:.4px}
#loading{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;
  background:var(--bg);color:var(--amber);font-size:14px;z-index:100}
</style>
</head>
<body>
<div id="loading">Loading&hellip;</div>
<div class="hdr">
  <span class="sym" id="sym"></span>
  <span class="nm"  id="nm"></span>
  <span class="price" id="price"></span>
</div>
<hr>
<div class="stats">
  <div><div class="stat-lbl">RSI (14)</div><div class="stat-val" id="s-rsi"></div></div>
  <div><div class="stat-lbl">MACD</div><div class="stat-val" id="s-macd"></div></div>
  <div><div class="stat-lbl">SIGNAL</div><div class="stat-val" id="s-sig"></div></div>
  <div><div class="stat-lbl">HISTOGRAM</div><div class="stat-val" id="s-hist"></div></div>
  <div><div class="stat-lbl">CROSSOVER</div><div class="stat-val" id="s-cross"></div></div>
</div>
<hr>
<div class="charts">
  <div class="cpanel" id="pw"><span class="clbl">CANDLESTICK &nbsp;&#x2500;&nbsp; EMA 20 &nbsp;&#x2500;&nbsp; EMA 50 &nbsp;&#x2500;&nbsp; VOLUME</span><div id="pc" style="height:100%"></div></div>
  <div class="cpanel" id="mw"><span class="clbl">MACD &nbsp;&#x2500;&nbsp; SIGNAL &nbsp;&#x2500;&nbsp; HISTOGRAM</span><div id="mc" style="height:100%"></div></div>
  <div class="cpanel" id="rw"><span class="clbl">RSI (14)</span><div id="rc" style="height:100%"></div></div>
</div>

<script>
const SYM = window.location.pathname.split('/').pop().toUpperCase();
document.title = SYM + ' \u2014 Chart';

const CLR = {
  bg:'#02020c', border:'#162a50', text:'#9ba3c0',
  amber:'#ffa000', abright:'#ffd23c',
  green:'#00e15f', red:'#ff3737', cyan:'#37c3ff', muted:'#4e536c'
};

function mkChart(el){
  return LightweightCharts.createChart(el, {
    width: el.clientWidth, height: el.clientHeight,
    layout:{background:{type:LightweightCharts.ColorType.Solid,color:CLR.bg},
            textColor:CLR.text,fontFamily:"Consolas,'Lucida Console',monospace",fontSize:11},
    grid:{vertLines:{color:CLR.border},horzLines:{color:CLR.border}},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
    timeScale:{borderColor:CLR.border,timeVisible:true,secondsVisible:false,rightOffset:4},
    rightPriceScale:{borderColor:CLR.border},
  });
}

// Sync time scales across all charts
let _syncing = false;
function syncTS(charts){
  charts.forEach(src=>{
    src.timeScale().subscribeVisibleLogicalRangeChange(r=>{
      if(_syncing||!r) return;
      _syncing=true;
      charts.forEach(d=>{ if(d!==src) d.timeScale().setVisibleLogicalRange(r); });
      _syncing=false;
    });
  });
}

// Sync crosshairs
function syncXH(pairs){
  pairs.forEach(([sc,ss])=>{
    sc.subscribeCrosshairMove(p=>{
      pairs.forEach(([dc,ds])=>{
        if(dc===sc) return;
        if(p.time){
          const v=p.seriesData.get(ss);
          dc.setCrosshairPosition(v?(v.close??v.value??0):0, p.time, ds);
        } else { dc.clearCrosshairPosition(); }
      });
    });
  });
}

async function load(){
  const r = await fetch('/api/chart/'+SYM);
  const d = await r.json();
  if(d.error){ document.getElementById('loading').textContent='Error: '+d.error; return; }

  // Header
  document.getElementById('sym').textContent   = d.symbol;
  document.getElementById('nm').textContent    = '\u00a0\u00a0'+d.name;
  document.getElementById('price').textContent = '$'+d.price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});

  const pn = v=>v>0?'pos':v<0?'neg':'neu';
  const f4 = v=>(v>=0?'+':'')+v.toFixed(4);
  const rsiCls = v=>v>=70?'neg':v<=30?'pos':'neu';

  document.getElementById('s-rsi').textContent  = d.rsi_val.toFixed(1);
  document.getElementById('s-rsi').className    = 'stat-val '+rsiCls(d.rsi_val);
  document.getElementById('s-macd').textContent = f4(d.macd_val);
  document.getElementById('s-macd').className   = 'stat-val '+pn(d.macd_val);
  document.getElementById('s-sig').textContent  = f4(d.signal_val);
  document.getElementById('s-sig').className    = 'stat-val '+pn(d.signal_val);
  document.getElementById('s-hist').textContent = f4(d.hist_val);
  document.getElementById('s-hist').className   = 'stat-val '+pn(d.hist_val);
  document.getElementById('s-cross').textContent= d.crossover?'BULLISH \u25b2':'BEARISH \u25bc';
  document.getElementById('s-cross').className  = 'stat-val '+(d.crossover?'pos':'neg');

  // ── Price chart ─────────────────────────────────────────────────────────────
  const pcEl = document.getElementById('pc');
  const pc   = mkChart(pcEl);

  const candles = pc.addCandlestickSeries({
    upColor:'#00e15f', downColor:'#ff3737',
    borderUpColor:'#00e15f', borderDownColor:'#ff3737',
    wickUpColor:'#00e15f', wickDownColor:'#ff3737',
  });
  candles.setData(d.candles);

  const vol = pc.addHistogramSeries({priceFormat:{type:'volume'},priceScaleId:'vol'});
  pc.priceScale('vol').applyOptions({scaleMargins:{top:0.82,bottom:0}});
  vol.setData(d.volumes);

  const e20 = pc.addLineSeries({color:CLR.cyan,   lineWidth:1.4,priceLineVisible:false,lastValueVisible:false});
  const e50 = pc.addLineSeries({color:CLR.abright,lineWidth:1.4,priceLineVisible:false,lastValueVisible:false,
                                 lineStyle:LightweightCharts.LineStyle.Dashed});
  e20.setData(d.ema20);
  e50.setData(d.ema50);

  // ── MACD chart ──────────────────────────────────────────────────────────────
  const mcEl = document.getElementById('mc');
  const mc   = mkChart(mcEl);

  const hist    = mc.addHistogramSeries({priceLineVisible:false,lastValueVisible:false});
  const macdLn  = mc.addLineSeries({color:CLR.cyan,   lineWidth:1.5,priceLineVisible:false,lastValueVisible:true});
  const sigLn   = mc.addLineSeries({color:CLR.abright,lineWidth:1.2,priceLineVisible:false,lastValueVisible:true,
                                     lineStyle:LightweightCharts.LineStyle.Dashed});
  hist.setData(d.hist);
  macdLn.setData(d.macd);
  sigLn.setData(d.signal);

  // ── RSI chart ───────────────────────────────────────────────────────────────
  const rcEl = document.getElementById('rc');
  const rc   = mkChart(rcEl);

  const rsiLn = rc.addLineSeries({color:CLR.cyan,lineWidth:1.5,priceLineVisible:false,lastValueVisible:true});
  rsiLn.setData(d.rsi);
  rsiLn.createPriceLine({price:70,color:CLR.red,  lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true,title:'OB'});
  rsiLn.createPriceLine({price:50,color:CLR.muted,lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dotted,axisLabelVisible:false});
  rsiLn.createPriceLine({price:30,color:CLR.green,lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true,title:'OS'});
  rc.priceScale('right').applyOptions({autoScale:false,minimum:0,maximum:100});

  // ── Sync + fit ───────────────────────────────────────────────────────────────
  syncTS([pc, mc, rc]);
  syncXH([[pc,candles],[mc,macdLn],[rc,rsiLn]]);
  [pc,mc,rc].forEach(c=>c.timeScale().fitContent());

  // ── Resize ───────────────────────────────────────────────────────────────────
  new ResizeObserver(()=>{
    pc.resize(pcEl.clientWidth, pcEl.clientHeight);
    mc.resize(mcEl.clientWidth, mcEl.clientHeight);
    rc.resize(rcEl.clientWidth, rcEl.clientHeight);
  }).observe(document.getElementById('pw'));

  document.getElementById('loading').style.display='none';
}

load();
</script>
</body>
</html>"""


# ── Portfolios page ──────────────────────────────────────────────────────────────
LEGIS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Legislation Tracker</title>
<style>
:root{
  --bg:#02020c;--bg-row:#04061414;--bg-alt:#080b1b;
  --hdr:#000212;--amber:#ffa000;--abright:#ffd23c;--adim:#825200;
  --white:#e1e1ee;--muted:#4e536c;--green:#00e15f;--red:#ff3737;
  --yellow:#ffd71e;--cyan:#37c3ff;--blue:#4fa3ff;--border:#162a50;
  --btn:#0a193c;--btnhov:#142d64;--btnact:#234696;
  --rep:#ff6b6b;--dem:#6b9fff;--ind:#b4ff6b;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{background:var(--bg);color:var(--white);
  font-family:Consolas,'Lucida Console','Courier New',monospace;
  font-size:13px;padding:12px 14px;display:flex;flex-direction:column}
.nav{display:flex;gap:0;margin-bottom:6px;border-bottom:1px solid var(--border);flex-shrink:0}
.nav a{color:var(--muted);text-decoration:none;padding:4px 14px;font-size:12px;letter-spacing:.6px;border-bottom:2px solid transparent;margin-bottom:-1px}
.nav a:hover{color:var(--amber)}
.nav a.active{color:var(--abright);border-bottom-color:var(--abright)}
.hdr{display:flex;align-items:baseline;gap:20px;margin-bottom:3px}
.title{color:var(--abright);font-size:19px;font-weight:bold;letter-spacing:.5px}
.subtitle{color:var(--adim);font-size:12px}
.clock{color:var(--muted);margin-left:auto;font-size:12px}
.tagline{color:var(--adim);font-size:11px;margin-bottom:6px}
hr{border:none;border-top:1px solid var(--border);margin:5px 0}
.controls{display:flex;align-items:center;flex-wrap:wrap;gap:3px;padding:5px 0}
.clabel{color:var(--muted);font-size:12px;margin:0 3px 0 8px}
.clabel:first-child{margin-left:0}
button{background:var(--btn);color:var(--white);border:1px solid var(--border);
  padding:3px 9px;cursor:pointer;font-family:inherit;font-size:12px;height:24px}
button:hover{background:var(--btnhov)}
button.active{background:var(--btnact);border-color:var(--adim);color:var(--abright)}
#search{background:#080c20;color:var(--white);border:1px solid var(--border);
  padding:3px 8px;font-family:inherit;font-size:12px;width:200px;height:24px}
#search::placeholder{color:var(--muted)}
#search:focus{outline:1px solid var(--adim)}
#lbl-status{color:var(--green);font-size:12px;margin-left:8px}
.tbl-wrap{flex:1;overflow:auto;border:1px solid var(--border);min-height:0}
table{width:100%;border-collapse:collapse;table-layout:fixed}
thead tr{background:var(--hdr);position:sticky;top:0;z-index:5}
th{color:var(--adim);text-align:left;padding:6px 8px;
  border-right:1px solid var(--border);border-bottom:2px solid var(--border);
  font-weight:normal;white-space:nowrap;font-size:12px}
th.sortable{cursor:pointer}
th.sortable:hover{color:var(--amber)}
th.sort-active{color:var(--abright)}
td{padding:4px 8px;border-right:1px solid #0d1830;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
tbody tr:nth-child(odd){background:var(--bg-row)}
tbody tr:nth-child(even){background:var(--bg-alt)}
tbody tr:hover{background:#0d1535}
.cn{width:40px}.cb{width:110px}.ct{min-width:220px}.cs{width:190px}
.ci{width:96px}.ch{width:56px}.csen{width:58px}.csg{width:56px}
.mc{color:var(--muted)}.bc{color:var(--abright)}.tc{color:var(--white)}
.sc{color:var(--white)}.dc{color:var(--muted)}
.chk-y{color:var(--green);font-size:15px;text-align:center}
.chk-n{color:var(--muted);text-align:center}
.party-r{color:var(--rep)}
.party-d{color:var(--dem)}
.party-i{color:var(--ind)}
.sbar{display:flex;gap:30px;padding:4px 0;font-size:11px;color:var(--muted);flex-shrink:0}
a.bill-link{color:var(--abright);text-decoration:none}
a.bill-link:hover{text-decoration:underline}
</style>
</head>
<body>
<div class="nav">
  <a href="/">LAUNCHPAD</a>
  <a href="/screener">SCREENER</a>
  <a href="/portfolios">PORTFOLIOS</a>
  <a href="/legis" class="active">LEGIS</a>
</div>
<div class="hdr">
  <span class="title">&#9672; LEGISLATION TRACKER</span>
  <span class="subtitle">119TH U.S. CONGRESS &middot; BILL STATUS</span>
  <span class="clock" id="clock"></span>
</div>
<div class="tagline">&nbsp;Source: GovTrack.us &mdash; Most recently active bills</div>
<div class="controls">
  <span class="clabel">ORIGIN:</span>
  <button class="active" data-group="chamber" data-val="ALL"  onclick="setFilter(this)">ALL</button>
  <button                data-group="chamber" data-val="HOUSE"   onclick="setFilter(this)">HOUSE</button>
  <button                data-group="chamber" data-val="SENATE"  onclick="setFilter(this)">SENATE</button>
  &nbsp;
  <span class="clabel">STATUS:</span>
  <button class="active" data-group="status" data-val="ALL"         onclick="setFilter(this)">ALL</button>
  <button                data-group="status" data-val="INTRODUCED"  onclick="setFilter(this)">INTRODUCED</button>
  <button                data-group="status" data-val="PROGRESS"    onclick="setFilter(this)">IN PROGRESS</button>
  <button                data-group="status" data-val="PASSED"      onclick="setFilter(this)">PASSED BOTH</button>
  <button                data-group="status" data-val="SIGNED"      onclick="setFilter(this)">SIGNED</button>
  &nbsp;
  <input id="search" type="text" placeholder="Search bill, title, sponsor..." oninput="debounceSearch()">
  <button onclick="doRefresh()">&#8635; REFRESH</button>
  <span id="lbl-status">&nbsp;READY</span>
</div>
<hr>
<div class="tbl-wrap">
  <table id="data-table">
    <thead><tr>
      <th class="cn">#</th>
      <th class="cb sortable sort-active" data-sort="date" onclick="thSort(this)">BILL &#9660;</th>
      <th class="ct">TITLE</th>
      <th class="cs sortable" data-sort="sponsor" onclick="thSort(this)">SPONSOR</th>
      <th class="ci sortable" data-sort="date" onclick="thSort(this)">INTRODUCED</th>
      <th class="ch" style="text-align:center">HOUSE</th>
      <th class="csen" style="text-align:center">SENATE</th>
      <th class="csg" style="text-align:center">SIGNED</th>
    </tr></thead>
    <tbody id="tbody"></tbody>
  </table>
</div>
<hr>
<div class="sbar">
  <span id="lbl-count"></span>
  <span id="lbl-updated"></span>
</div>

<script>
const S={chamber:'ALL',status:'ALL',sortKey:'date',sortDir:'desc',search:''};
let searchTimer=null;

function tick(){const n=new Date();document.getElementById('clock').textContent=n.toTimeString().slice(0,8);}
setInterval(tick,1000);tick();

function setFilter(btn){
  const g=btn.dataset.group,v=btn.dataset.val;
  document.querySelectorAll(`[data-group="${g}"]`).forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  if(g==='chamber') S.chamber=v;
  if(g==='status')  S.status=v;
  fetchAndRender();
}

function thSort(th){
  const k=th.dataset.sort;
  if(S.sortKey===k) S.sortDir=S.sortDir==='desc'?'asc':'desc';
  else{S.sortKey=k;S.sortDir='desc';}
  document.querySelectorAll('th.sort-active').forEach(t=>t.classList.remove('sort-active'));
  th.classList.add('sort-active');
  fetchAndRender();
}

function debounceSearch(){
  clearTimeout(searchTimer);
  searchTimer=setTimeout(()=>{S.search=document.getElementById('search').value;fetchAndRender();},300);
}

function chk(val){
  return val
    ? '<span class="chk-y">&#10003;</span>'
    : '<span class="chk-n">&ndash;</span>';
}

function partyCls(p){
  if(p==='R') return 'party-r';
  if(p==='D') return 'party-d';
  return 'party-i';
}

let legisPoller=null;

async function fetchAndRender(){
  const p=new URLSearchParams({chamber:S.chamber,status:S.status,sort:S.sortKey,dir:S.sortDir,q:S.search});
  const r=await fetch('/api/legis?'+p);
  const d=await r.json();
  renderTable(d.bills, d.total, d.loading);
  clearTimeout(legisPoller);
  if(d.loading) legisPoller=setTimeout(fetchAndRender,4000);
  document.getElementById('lbl-updated').textContent='  Updated: '+new Date().toTimeString().slice(0,8);
}

function renderTable(rows, total, loading){
  const st=document.getElementById('lbl-status');
  if(loading){st.textContent='  LOADING...';st.style.color='var(--amber)';}
  else{st.textContent='  READY';st.style.color='var(--green)';}
  document.getElementById('lbl-count').textContent=`  Showing ${rows.length} of ${total} bills`;
  const tbody=document.getElementById('tbody');
  if(!rows.length){
    tbody.innerHTML=`<tr><td colspan="8" style="color:var(--muted);padding:20px">&nbsp;${loading?'Fetching bill data from GovTrack...':'No bills match the current filters.'}</td></tr>`;
    return;
  }
  tbody.innerHTML=rows.map((r,i)=>`<tr>
    <td class="cn mc">&nbsp;${i+1}</td>
    <td class="cb bc">&nbsp;<a class="bill-link" href="${r.link}" target="_blank">${r.bill_number}</a></td>
    <td class="ct tc" title="${r.title}">&nbsp;${r.title}</td>
    <td class="cs" style="color:inherit">&nbsp;<span class="${partyCls(r.party)}">[${r.party}]</span> ${r.sponsor}</td>
    <td class="ci dc">&nbsp;${r.introduced}</td>
    <td class="ch" style="text-align:center">${chk(r.house_passed)}</td>
    <td class="csen" style="text-align:center">${chk(r.senate_passed)}</td>
    <td class="csg" style="text-align:center">${chk(r.signed)}</td>
  </tr>`).join('');
}

async function doRefresh(){
  document.getElementById('lbl-status').textContent='  REFRESHING...';
  document.getElementById('lbl-status').style.color='var(--amber)';
  await fetch('/api/legis/refresh',{method:'POST'});
  await new Promise(r=>setTimeout(r,2000));
  await fetchAndRender();
  document.getElementById('lbl-status').textContent='  READY';
  document.getElementById('lbl-status').style.color='var(--green)';
}

fetchAndRender();
</script>
</body>
</html>"""


PORTFOLIOS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Government Portfolios</title>
<style>
:root{
  --bg:#02020c;--bg-row:#04061414;--bg-alt:#080b1b;
  --hdr:#000212;--amber:#ffa000;--abright:#ffd23c;--adim:#825200;
  --white:#e1e1ee;--muted:#4e536c;--green:#00e15f;--red:#ff3737;
  --yellow:#ffd71e;--cyan:#37c3ff;--border:#162a50;
  --btn:#0a193c;--btnhov:#142d64;--btnact:#234696;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{background:var(--bg);color:var(--white);
  font-family:Consolas,'Lucida Console','Courier New',monospace;
  font-size:13px;padding:12px 14px;display:flex;flex-direction:column}
.nav{display:flex;gap:0;margin-bottom:6px;border-bottom:1px solid var(--border);flex-shrink:0}
.nav a{color:var(--muted);text-decoration:none;padding:4px 14px;font-size:12px;letter-spacing:.6px;border-bottom:2px solid transparent;margin-bottom:-1px}
.nav a:hover{color:var(--amber)}
.nav a.active{color:var(--abright);border-bottom-color:var(--abright)}
.hdr{display:flex;align-items:baseline;gap:20px;margin-bottom:3px}
.title{color:var(--abright);font-size:19px;font-weight:bold;letter-spacing:.5px}
.subtitle{color:var(--adim);font-size:12px}
.clock{color:var(--muted);margin-left:auto;font-size:12px}
.tagline{color:var(--adim);font-size:11px;margin-bottom:6px}
hr{border:none;border-top:1px solid var(--border);margin:5px 0}
.controls{display:flex;align-items:center;flex-wrap:wrap;gap:3px;padding:5px 0}
.clabel{color:var(--muted);font-size:12px;margin:0 3px 0 8px}
.clabel:first-child{margin-left:0}
.sp{width:10px;display:inline-block}
button{background:var(--btn);color:var(--white);border:1px solid var(--border);
  padding:3px 9px;cursor:pointer;font-family:inherit;font-size:12px;height:24px}
button:hover{background:var(--btnhov)}
button.active{background:var(--btnact);border-color:var(--adim);color:var(--abright)}
#search{background:#080c20;color:var(--white);border:1px solid var(--border);
  padding:3px 8px;font-family:inherit;font-size:12px;width:160px;height:24px}
#search::placeholder{color:var(--muted)}
#search:focus{outline:1px solid var(--adim)}
#lbl-status{color:var(--amber);font-size:12px;margin-left:8px}
.tbl-wrap{flex:1;overflow:auto;border:1px solid var(--border);min-height:0}
table{width:100%;border-collapse:collapse;table-layout:fixed}
thead tr{background:var(--hdr);position:sticky;top:0;z-index:5}
th{color:var(--adim);text-align:left;padding:6px 8px;
  border-right:1px solid var(--border);border-bottom:2px solid var(--border);
  font-weight:normal;white-space:nowrap;font-size:12px}
th.sortable{cursor:pointer}
th.sortable:hover{color:var(--amber)}
th.sort-active{color:var(--abright)}
td{padding:4px 8px;border-right:1px solid #0d1830;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
tbody tr:nth-child(odd){background:var(--bg-row)}
tbody tr:nth-child(even){background:var(--bg-alt)}
tbody tr:hover{background:#0d1535}
.cn{width:44px}.cc{width:170px}.ch{width:70px}
.ct{width:76px}.co{width:220px}.ctp{width:90px}
.cam{width:170px}.cd{width:96px}
.mc{color:var(--muted)}.nc{color:var(--white)}.tc{color:var(--abright)}
.hc{color:var(--cyan)}.sc{color:var(--adim)}.dc{color:var(--muted)}
.buy{color:var(--green);font-weight:bold}
.sell{color:var(--red);font-weight:bold}
.exch{color:var(--yellow)}
.sbar{display:flex;align-items:center;gap:20px;font-size:11px;padding:4px 0}
#lbl-count{color:var(--adim)}
#lbl-updated{color:var(--muted)}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:#1e3258;border-radius:2px}
</style>
</head>
<body>
<div class="nav">
  <a href="/">LAUNCHPAD</a>
  <a href="/screener">SCREENER</a>
  <a href="/portfolios" class="active">PORTFOLIOS</a>
  <a href="/legis">LEGIS</a>
</div>
<div class="hdr">
  <span class="title">&#9672; GOVERNMENT PORTFOLIOS</span>
  <span class="subtitle">CONGRESSIONAL STOCK DISCLOSURES</span>
  <span class="clock" id="clock"></span>
</div>
<div class="tagline">&nbsp;&nbsp;STOCK Act Disclosures &middot; House &amp; Senate &middot; Source: House/Senate Stock Watcher</div>
<hr>
<div class="controls">
  <span class="clabel">CHAMBER:</span>
  <button class="active" data-group="chamber" data-val="ALL"    onclick="setFilter(this)"> ALL </button>
  <button               data-group="chamber" data-val="HOUSE"  onclick="setFilter(this)"> HOUSE </button>
  <button               data-group="chamber" data-val="SENATE" onclick="setFilter(this)"> SENATE </button>

  <span class="sp"></span>
  <span class="clabel">TYPE:</span>
  <button class="active" data-group="type" data-val="ALL"      onclick="setFilter(this)"> ALL </button>
  <button               data-group="type" data-val="PURCHASE" onclick="setFilter(this)"> PURCHASE </button>
  <button               data-group="type" data-val="SALE"      onclick="setFilter(this)"> SALE </button>
  <button               data-group="type" data-val="EXCHANGE"  onclick="setFilter(this)"> EXCHANGE </button>

  <span class="sp"></span>
  <span class="clabel">SORT:</span>
  <button data-sort="date"   onclick="setSort(this)"> DATE </button>
  <button data-sort="amount" onclick="setSort(this)"> AMOUNT </button>
  <button data-sort="name"   onclick="setSort(this)"> NAME </button>
  <button data-sort="ticker" onclick="setSort(this)"> TICKER </button>

  <span class="sp"></span>
  <span class="clabel">SEARCH:</span>
  <input id="search" type="text" placeholder="name, ticker, company" oninput="debounceSearch()">

  <span class="sp"></span>
  <button onclick="doRefresh()"> REFRESH </button>
  <span id="lbl-status"></span>
</div>
<hr>

<div class="tbl-wrap">
  <table id="data-table">
    <thead><tr>
      <th class="cn">#</th>
      <th class="cc sortable" data-sort="name"   onclick="thSort(this)">CONGRESSMAN</th>
      <th class="ch">CHAMBER</th>
      <th class="ct sortable" data-sort="ticker" onclick="thSort(this)">TICKER</th>
      <th class="co">COMPANY</th>
      <th class="ctp">TYPE</th>
      <th class="cam sortable" data-sort="amount" onclick="thSort(this)">AMOUNT</th>
      <th class="cd sortable sort-active" data-sort="date" onclick="thSort(this)">DATE &#9660;</th>
    </tr></thead>
    <tbody id="tbody"></tbody>
  </table>
</div>
<hr>
<div class="sbar">
  <span id="lbl-count"></span>
  <span id="lbl-updated"></span>
</div>

<script>
const S={chamber:'ALL',ttype:'ALL',sortKey:'date',sortDir:'desc',search:''};
let searchTimer=null;

function tick(){const n=new Date();document.getElementById('clock').textContent=n.toTimeString().slice(0,8);}
setInterval(tick,1000);tick();

function setFilter(btn){
  const g=btn.dataset.group,v=btn.dataset.val;
  document.querySelectorAll(`[data-group="${g}"]`).forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  if(g==='chamber') S.chamber=v;
  if(g==='type')    S.ttype=v;
  fetchAndRender();
}

function setSort(btn){
  const k=btn.dataset.sort;
  if(S.sortKey===k) S.sortDir=S.sortDir==='desc'?'asc':'desc';
  else{S.sortKey=k;S.sortDir=k==='date'?'desc':'asc';}
  fetchAndRender();
}

function thSort(th){setSort({dataset:{sort:th.dataset.sort}});}

function debounceSearch(){
  clearTimeout(searchTimer);
  searchTimer=setTimeout(()=>{S.search=document.getElementById('search').value;fetchAndRender();},300);
}

function typeCls(t){
  if(!t) return '';
  if(t.includes('PURCHASE')) return 'buy';
  if(t.includes('SALE'))     return 'sell';
  return 'exch';
}

let pollTimer=null;

async function fetchAndRender(){
  const p=new URLSearchParams({chamber:S.chamber,ttype:S.ttype,sort:S.sortKey,dir:S.sortDir,q:S.search});
  const r=await fetch('/api/portfolios?'+p);
  const d=await r.json();
  renderTable(d.trades, d.total, d.loading);
  // If still loading, poll every 5 seconds
  clearTimeout(pollTimer);
  if(d.loading) pollTimer=setTimeout(fetchAndRender, 5000);
}

function renderTable(rows, total, loading){
  const countEl=document.getElementById('lbl-count');
  const statusEl=document.getElementById('lbl-status');
  if(loading){
    statusEl.textContent='  LOADING DISCLOSURES...';
    statusEl.style.color='var(--amber)';
  } else {
    statusEl.textContent='  READY';
    statusEl.style.color='var(--green)';
  }
  countEl.textContent=`  Showing ${rows.length} of ${total} disclosures`;
  const tbody=document.getElementById('tbody');
  if(!rows.length){
    tbody.innerHTML=`<tr><td colspan="8" style="color:var(--muted);padding:20px">${loading?'  Downloading House STOCK Act disclosures from official records... please wait.':'  No records match the current filters.'}</td></tr>`;
    return;
  }
  tbody.innerHTML=rows.map((r,i)=>`<tr>
    <td class="cn mc">&nbsp;${i+1}</td>
    <td class="cc nc">&nbsp;${r.source_url
      ? `<a href="${r.source_url}" target="_blank" rel="noopener" title="View source disclosure PDF" style="color:var(--abright);text-decoration:none;">${r.name} &#x1F517;</a>`
      : r.name}</td>
    <td class="ch hc">&nbsp;${r.chamber}</td>
    <td class="ct tc">&nbsp;${r.ticker}</td>
    <td class="co nc">&nbsp;${r.company}</td>
    <td class="ctp ${typeCls(r.trade_type)}">&nbsp;${r.trade_type}</td>
    <td class="cam sc">&nbsp;${r.amount}</td>
    <td class="cd dc">&nbsp;${r.transaction_date}</td>
  </tr>`).join('');
}

async function doRefresh(){
  document.getElementById('lbl-status').textContent='  REFRESHING...';
  document.getElementById('lbl-status').style.color='var(--amber)';
  await fetch('/api/portfolios/refresh',{method:'POST'});
  await fetchAndRender();
  document.getElementById('lbl-status').textContent='  READY';
  document.getElementById('lbl-status').style.color='var(--green)';
  document.getElementById('lbl-updated').textContent='  Updated: '+new Date().toTimeString().slice(0,8);
}

fetchAndRender();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return LAUNCHPAD_HTML


def _free_port(port: int):
    """Kill whatever process is holding the given port, so startup never fails."""
    try:
        result = subprocess.check_output(
            f'netstat -ano | findstr ":{port} "', shell=True, text=True
        )
        for line in result.splitlines():
            parts = line.split()
            if len(parts) >= 5 and f":{port}" in parts[1] and parts[3] == "LISTENING":
                pid = int(parts[4])
                if pid > 4:  # skip System/Idle
                    subprocess.call(f"taskkill /PID {pid} /F", shell=True,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print(f"[startup] Freed port {port} (killed PID {pid})")
                    time.sleep(0.5)
    except Exception:
        pass  # port was already free


if __name__ == "__main__":
    _free_port(8888)
    trigger_refresh()
    threading.Thread(target=_bg_congress, daemon=True).start()
    threading.Thread(target=_bg_bills,   daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8888, log_level="warning")