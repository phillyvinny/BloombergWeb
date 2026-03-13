"""
Bloomberg-Style Stock Intelligence Terminal — Web Edition
FastAPI backend · Bloomberg dark UI · Auto-refresh every 5 min
Run:  python bloomberg_web.py   →   open http://localhost:8000
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import numpy as np
import requests
import yfinance as yf
import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, Response

# ── Config ──────────────────────────────────────────────────────────────────────
YAHOO_CHART_URL  = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS          = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
REFRESH_INTERVAL = 300
MAX_WORKERS      = 20
SCORE_BUY        = 65
SCORE_WATCH      = 40

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
    try:
        info = yf.Ticker(sym).info
        mean = info.get("recommendationMean")
        n    = info.get("numberOfAnalystOpinions", 0)
        return float(mean) if (mean is not None and n >= 2) else None
    except Exception:
        return None


def _bar(score, mx=20):
    filled = max(0, min(8, round(score / mx * 8)))
    return "\u2588" * filled + "\u2591" * (8 - filled)


def _fetch_one(sym, idx):
    try:
        r = requests.get(
            YAHOO_CHART_URL.format(symbol=sym),
            params={"interval": "1d", "range": "3mo"},
            headers=HEADERS, timeout=10,
        )
        r.raise_for_status()
        res    = r.json()["chart"]["result"][0]
        meta   = res["meta"]
        closes = [c for c in res["indicators"]["quote"][0].get("close", []) if c is not None]
        sc     = _score(closes)
        if sc is None:
            return None
        analyst_mean = _fetch_analyst(sym)
        analyst_s    = _analyst_score(analyst_mean)
        total        = sc["total"] + analyst_s
        signal       = "BUY" if total >= SCORE_BUY else ("WATCH" if total >= SCORE_WATCH else "NO BUY")
        return {
            "symbol":       sym,
            "name":         (meta.get("longName") or meta.get("shortName") or sym)[:32],
            "price":        float(meta.get("regularMarketPrice") or (closes[-1] if closes else 0)),
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
            # Pre-rendered bar strings
            "bar_ema":      _bar(sc["ema_s"]),
            "bar_macd":     _bar(sc["macd_s"]),
            "bar_rsi":      _bar(sc["rsi_s"]),
            "bar_trend":    _bar(sc["trend_s"]),
            "bar_analyst":  _bar(analyst_s) if analyst_mean is not None else "\u2591" * 8,
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

# ── MACD Chart Data ──────────────────────────────────────────────────────────────
def _compute_chart_data(sym):
    """Fetch 6 months of daily data and return full MACD series for charting."""
    r = requests.get(
        YAHOO_CHART_URL.format(symbol=sym),
        params={"interval": "1d", "range": "6mo"},
        headers=HEADERS, timeout=15,
    )
    r.raise_for_status()
    result = r.json()["chart"]["result"][0]
    meta   = result["meta"]
    timestamps = result.get("timestamp", [])
    quote      = result["indicators"]["quote"][0]
    closes_raw = quote.get("close", [])

    pairs = [(t, c) for t, c in zip(timestamps, closes_raw) if c is not None]
    if len(pairs) < 35:
        return None

    dates  = [datetime.fromtimestamp(t).strftime("%b %d") for t, _ in pairs]
    closes = [float(c) for _, c in pairs]

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd  = [a - b for a, b in zip(ema12, ema26)]
    sig   = _ema(macd, 9)
    hist  = [m - s for m, s in zip(macd, sig)]

    return {
        "symbol":     sym,
        "name":       (meta.get("longName") or meta.get("shortName") or sym),
        "dates":      dates,
        "prices":     [round(c, 2) for c in closes],
        "ema12":      [round(v, 4) for v in ema12],
        "ema26":      [round(v, 4) for v in ema26],
        "macd":       [round(v, 4) for v in macd],
        "signal":     [round(v, 4) for v in sig],
        "hist":       [round(v, 4) for v in hist],
        "macd_val":   round(macd[-1], 4),
        "signal_val": round(sig[-1], 4),
        "hist_val":   round(hist[-1], 4),
        "price":      round(closes[-1], 2),
        "crossover":  macd[-1] > sig[-1],
    }


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


# ── HTML page ────────────────────────────────────────────────────────────────────
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bloomberg Intelligence Terminal</title>
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
.macd-cell{cursor:pointer}
.macd-cell:hover{background:#122040 !important;color:#a0e8ff !important}
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
      <th class="c8">ANLYST/20</th>
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
    const aBars=am!=null?`${s.bar_analyst}&nbsp;${String(s.analyst_s).padStart(2)}/20`
                        :`${s.bar_analyst}&nbsp;&nbsp;N/A`;
    return `<tr>
      <td class="c0 mc">&nbsp;${i+1}</td>
      <td class="c1 tc">&nbsp;${s.symbol}</td>
      <td class="c2 nc">&nbsp;${s.name}</td>
      <td class="c3 pc">$${fmt(s.price)}&nbsp;</td>
      <td class="c4 bc">${s.bar_ema}&nbsp;${String(s.ema_s).padStart(2)}/20</td>
      <td class="c5 bc macd-cell" onclick="openChart('${s.symbol}')" title="Click to open MACD chart">${s.bar_macd}&nbsp;${String(s.macd_s).padStart(2)}/20</td>
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
      startCountdown(st.next_refresh);
      await fetchAndRender();
      // schedule next auto-refresh
      setTimeout(manualRefresh, st.next_refresh*1000);
    }
  } catch(e){
    S.pollTimer=setTimeout(pollStatus,2000);
  }
}

// ── Manual refresh ─────────────────────────────────────────────────────────────
function openChart(symbol){
  window.open('/chart/'+symbol,'macd_'+symbol,
    'width=1060,height=720,resizable=yes,scrollbars=no,menubar=no,toolbar=no');
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
<title>MACD Chart</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
:root{
  --bg:#02020c;--hdr:#000212;--amber:#ffa000;--abright:#ffd23c;--adim:#825200;
  --white:#e1e1ee;--muted:#4e536c;--green:#00e15f;--red:#ff3737;
  --yellow:#ffd71e;--cyan:#37c3ff;--border:#162a50;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;background:var(--bg);color:var(--white);
  font-family:Consolas,'Lucida Console','Courier New',monospace;font-size:13px}
body{display:flex;flex-direction:column;padding:12px 16px;gap:0}
.hdr{display:flex;align-items:baseline;gap:16px;margin-bottom:6px}
.sym{color:var(--abright);font-size:20px;font-weight:bold}
.nm{color:var(--adim);font-size:13px}
.price{color:var(--amber);margin-left:auto;font-size:15px}
hr{border:none;border-top:1px solid var(--border);margin:5px 0}
/* stats strip */
.stats{display:flex;gap:28px;padding:7px 2px;font-size:12px}
.stat-lbl{color:var(--muted)}
.stat-val{font-size:14px;font-weight:bold}
.pos{color:var(--green)}.neg{color:var(--red)}.neu{color:var(--yellow)}
/* chart containers */
.charts{flex:1;display:flex;flex-direction:column;gap:6px;min-height:0}
.chart-box{position:relative;background:#04060f;border:1px solid var(--border);border-radius:2px}
.chart-label{position:absolute;top:6px;left:10px;font-size:11px;color:var(--adim);z-index:1;pointer-events:none}
#price-box{flex:1.2}
#macd-box{flex:1}
canvas{display:block}
/* loading */
#loading{display:flex;align-items:center;justify-content:center;
  position:absolute;inset:0;background:var(--bg);color:var(--amber);font-size:14px;z-index:10}
#err{display:none;color:var(--red);padding:20px}
</style>
</head>
<body>
<div id="loading">Loading chart data&hellip;</div>

<div class="hdr">
  <span class="sym" id="sym"></span>
  <span class="nm"  id="nm"></span>
  <span class="price" id="price"></span>
</div>
<hr>
<div class="stats">
  <div>
    <div class="stat-lbl">MACD</div>
    <div class="stat-val" id="s-macd"></div>
  </div>
  <div>
    <div class="stat-lbl">SIGNAL</div>
    <div class="stat-val" id="s-sig"></div>
  </div>
  <div>
    <div class="stat-lbl">HISTOGRAM</div>
    <div class="stat-val" id="s-hist"></div>
  </div>
  <div>
    <div class="stat-lbl">CROSSOVER</div>
    <div class="stat-val" id="s-cross"></div>
  </div>
</div>
<hr>
<div class="charts">
  <div class="chart-box" id="price-box">
    <span class="chart-label">PRICE &nbsp;&#x2014;&nbsp; EMA12 &nbsp;&#x2014;&nbsp; EMA26</span>
    <canvas id="price-chart"></canvas>
  </div>
  <div class="chart-box" id="macd-box">
    <span class="chart-label">MACD &nbsp;&#x2014;&nbsp; SIGNAL &nbsp;&#x2014;&nbsp; HISTOGRAM</span>
    <canvas id="macd-chart"></canvas>
  </div>
</div>
<div id="err"></div>

<script>
const SYMBOL = window.location.pathname.split('/').pop().toUpperCase();
document.title = 'MACD \u2014 ' + SYMBOL;

const GRID   = 'rgba(22,42,80,0.6)';
const TICK   = '#4e536c';
const TOOLTIP_BG = '#050a1e';

function baseScaleOpts(type='linear'){
  return {
    type,
    grid:{color:GRID},
    ticks:{color:TICK,maxRotation:0,autoSkipPadding:12},
    border:{color:GRID}
  };
}

function basePlugins(legend=true){
  return {
    legend: legend
      ? {labels:{color:'#9ba3c0',font:{size:11},boxWidth:20,padding:12}}
      : {display:false},
    tooltip:{
      backgroundColor:TOOLTIP_BG,titleColor:'#ffd23c',
      bodyColor:'#c0c8e8',borderColor:'#162a50',borderWidth:1
    }
  };
}

async function load(){
  const r = await fetch('/api/chart/'+SYMBOL);
  const d = await r.json();
  if(d.error){
    document.getElementById('err').style.display='block';
    document.getElementById('err').textContent='Error: '+d.error;
    document.getElementById('loading').style.display='none';
    return;
  }

  // populate header & stats
  document.getElementById('sym').textContent   = d.symbol;
  document.getElementById('nm').textContent    = d.name;
  document.getElementById('price').textContent = '$'+d.price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});

  const posNeg = v => v > 0 ? 'pos' : v < 0 ? 'neg' : 'neu';
  const fmt4   = v => (v >= 0 ? '+' : '') + v.toFixed(4);

  document.getElementById('s-macd').textContent  = fmt4(d.macd_val);
  document.getElementById('s-macd').className    = 'stat-val ' + posNeg(d.macd_val);
  document.getElementById('s-sig').textContent   = fmt4(d.signal_val);
  document.getElementById('s-sig').className     = 'stat-val ' + posNeg(d.signal_val);
  document.getElementById('s-hist').textContent  = fmt4(d.hist_val);
  document.getElementById('s-hist').className    = 'stat-val ' + posNeg(d.hist_val);
  document.getElementById('s-cross').textContent = d.crossover ? 'BULLISH \u25b2' : 'BEARISH \u25bc';
  document.getElementById('s-cross').className   = 'stat-val ' + (d.crossover ? 'pos' : 'neg');

  // size canvases to fill containers
  const priceBox = document.getElementById('price-box');
  const macdBox  = document.getElementById('macd-box');

  // ── Price chart ───────────────────────────────────────────────────────────
  const pc = document.getElementById('price-chart');
  new Chart(pc, {
    type: 'line',
    data: {
      labels: d.dates,
      datasets: [
        {
          label: 'Price',
          data: d.prices,
          borderColor: '#ffa000',
          borderWidth: 1.8,
          pointRadius: 0,
          tension: 0.15,
          fill: false,
          order: 1,
        },
        {
          label: 'EMA 12',
          data: d.ema12,
          borderColor: '#37c3ff',
          borderWidth: 1.2,
          pointRadius: 0,
          borderDash: [],
          tension: 0.15,
          fill: false,
          order: 2,
        },
        {
          label: 'EMA 26',
          data: d.ema26,
          borderColor: '#ffd23c',
          borderWidth: 1.2,
          pointRadius: 0,
          borderDash: [4,3],
          tension: 0.15,
          fill: false,
          order: 3,
        },
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: basePlugins(true),
      scales: {
        x: {...baseScaleOpts('category'), ticks:{...baseScaleOpts('category').ticks, maxTicksLimit:12}},
        y: {...baseScaleOpts(), position:'right',
          ticks:{...baseScaleOpts().ticks, callback: v=>'$'+v.toLocaleString()}}
      }
    }
  });

  // ── MACD chart ────────────────────────────────────────────────────────────
  const histColors = d.hist.map(v => v >= 0 ? 'rgba(0,225,95,0.75)' : 'rgba(255,55,55,0.75)');
  const mc = document.getElementById('macd-chart');
  new Chart(mc, {
    data: {
      labels: d.dates,
      datasets: [
        {
          type: 'bar',
          label: 'Histogram',
          data: d.hist,
          backgroundColor: histColors,
          borderWidth: 0,
          order: 3,
        },
        {
          type: 'line',
          label: 'MACD',
          data: d.macd,
          borderColor: '#37c3ff',
          borderWidth: 1.6,
          pointRadius: 0,
          tension: 0.1,
          fill: false,
          order: 1,
        },
        {
          type: 'line',
          label: 'Signal',
          data: d.signal,
          borderColor: '#ffd23c',
          borderWidth: 1.4,
          pointRadius: 0,
          borderDash: [4,3],
          tension: 0.1,
          fill: false,
          order: 2,
        },
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: basePlugins(true),
      scales: {
        x: {...baseScaleOpts('category'), ticks:{...baseScaleOpts('category').ticks, maxTicksLimit:12}},
        y: {...baseScaleOpts(), position:'right',
          ticks:{...baseScaleOpts().ticks, callback: v=>v.toFixed(3)}}
      }
    }
  });

  document.getElementById('loading').style.display = 'none';
}

load();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


if __name__ == "__main__":
    trigger_refresh()
    uvicorn.run(app, host="127.0.0.1", port=8888, log_level="warning")
