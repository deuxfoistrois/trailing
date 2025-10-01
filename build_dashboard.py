# build_dashboard.py — dashboard con trailing detail (High-Water & Dynamic Stop)
import os, csv, json, pathlib, datetime
from collections import defaultdict, deque
from decimal import Decimal

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus, OrderType

# --- Conexión (paper) ---
API_KEY = os.environ["APCA_API_KEY_ID"]
API_SECRET = os.environ["APCA_API_SECRET_KEY"]
client = TradingClient(API_KEY, API_SECRET, paper=True)

# --- Paths ---
ROOT = pathlib.Path(__file__).resolve().parent
DOCS = ROOT / "docs"
DATA = ROOT / "data"
DOCS.mkdir(exist_ok=True)
DATA.mkdir(exist_ok=True)

HIST_EQUITY = DATA / "equity_history.csv"
HIST_POS = DATA / "pos_history.csv"    # histórico por símbolo
OUT_HTML = DOCS / "index.html"

def d2(x):
    return float(Decimal(str(x)).quantize(Decimal("0.01")))

def now_iso():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat()+"Z"

# --- Datos de cuenta/posiciones/órdenes ---
account = client.get_account()
positions = client.get_all_positions()
open_orders = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))

timestamp = now_iso()
portfolio_value = float(account.portfolio_value)
cash = float(account.cash)
buying_power = float(account.buying_power)
last_equity = float(account.last_equity) if account.last_equity is not None else portfolio_value

# --- Actualizar equity_history.csv (intraday) ---
write_header_eq = not HIST_EQUITY.exists()
append_eq = True
if HIST_EQUITY.exists():
    try:
        with HIST_EQUITY.open("r", newline="") as f:
            rows = list(csv.reader(f))
            if rows and rows[-1] and rows[-1][0] == timestamp:
                append_eq = False
    except Exception:
        pass

if append_eq:
    with HIST_EQUITY.open("a", newline="") as f:
        w = csv.writer(f)
        if write_header_eq:
            w.writerow(["timestamp","portfolio_value","last_equity","cash","buying_power"])
        w.writerow([timestamp, f"{portfolio_value:.2f}", f"{last_equity:.2f}", f"{cash:.2f}", f"{buying_power:.2f}"])

# --- Actualizar pos_history.csv (una fila por símbolo) ---
write_header_pos = not HIST_POS.exists()
with HIST_POS.open("a", newline="") as f:
    w = csv.writer(f)
    if write_header_pos:
        w.writerow(["timestamp","symbol","qty","avg_entry","current","market_value","unreal_pl","unreal_plpc"])
    for p in positions:
        w.writerow([
            timestamp,
            p.symbol,
            f"{float(p.qty):.8f}",
            f"{d2(p.avg_entry_price):.2f}",
            f"{d2(p.current_price):.2f}",
            f"{d2(p.market_value):.2f}",
            f"{d2(p.unrealized_pl) if p.unrealized_pl is not None else 0.0:.2f}",
            f"{float(p.unrealized_plpc) if p.unrealized_plpc is not None else 0.0:.6f}",
        ])

# --- Preparar datos actuales para tablas ---
pos_rows = []
for p in positions:
    pos_rows.append({
        "symbol": p.symbol,
        "qty": float(p.qty),
        "avg_entry": d2(p.avg_entry_price),
        "current": d2(p.current_price),
        "market_value": d2(p.market_value),
        "unreal_pl": d2(p.unrealized_pl) if p.unrealized_pl is not None else 0.0,
        "unreal_plpc": float(p.unrealized_plpc) if p.unrealized_plpc is not None else 0.0,
    })

# Órdenes abiertas → trailing / stop / general
orders_rows, trailing_rows, fixed_stop_rows = [], [], []
for o in open_orders:
    oid = o.id
    sym = o.symbol
    side = getattr(o, "side", None).value if getattr(o, "side", None) else ""
    otype = getattr(o, "type", None).value if getattr(o, "type", None) else ""
    qty = float(getattr(o, "qty", 0.0)) if getattr(o, "qty", None) is not None else None
    status = getattr(o, "status", None).value if getattr(o, "status", None) else ""
    submitted_at = o.submitted_at.isoformat() if getattr(o, "submitted_at", None) else ""

    orders_rows.append({
        "id": oid, "symbol": sym, "side": side, "type": otype,
        "qty": qty, "status": status, "submitted_at": submitted_at
    })

    if getattr(o, "type", None) == OrderType.TRAILING_STOP:
        trail_percent = getattr(o, "trail_percent", None)
        trail_price = getattr(o, "trail_price", None)  # puede venir None en paper
        trailing_rows.append({
            "id": oid, "symbol": sym, "qty": qty,
            "trail_percent": float(trail_percent) if trail_percent is not None else None,
            "trail_price": d2(trail_price) if trail_price is not None else None,
            "status": status, "submitted_at": submitted_at
        })

    if getattr(o, "type", None) == OrderType.STOP:
        stop_price = getattr(o, "stop_price", None)
        fixed_stop_rows.append({
            "id": oid, "symbol": sym, "qty": qty,
            "stop_price": d2(stop_price) if stop_price is not None else None,
            "status": status, "submitted_at": submitted_at
        })

# --- Cargar históricos para gráficos ---
equity_labels_intraday, equity_values_intraday = [], []
if HIST_EQUITY.exists():
    with HIST_EQUITY.open("r", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            equity_labels_intraday.append(row["timestamp"])
            equity_values_intraday.append(float(row["portfolio_value"]))

# Serie diaria (último valor por fecha UTC)
daily_last_by_date = {}
if HIST_EQUITY.exists():
    with HIST_EQUITY.open("r", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            date = row["timestamp"][:10]
            daily_last_by_date[date] = float(row["portfolio_value"])
equity_labels_daily = sorted(daily_last_by_date.keys())
equity_values_daily = [daily_last_by_date[d] for d in equity_labels_daily]

# Por símbolo: históricos para gráfico individual + para trailing detail
MAX_POINTS_PER_SYMBOL = 5000
symbol_series = defaultdict(lambda: {"t": deque(maxlen=MAX_POINTS_PER_SYMBOL),
                                     "price": deque(maxlen=MAX_POINTS_PER_SYMBOL),
                                     "plpc": deque(maxlen=MAX_POINTS_PER_SYMBOL)})
if HIST_POS.exists():
    with HIST_POS.open("r", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            sym = row["symbol"]
            symbol_series[sym]["t"].append(row["timestamp"])
            symbol_series[sym]["price"].append(float(row["current"]))
            symbol_series[sym]["plpc"].append(float(row["unreal_plpc"]) * 100.0)

symbol_history = {sym: {"t": list(ser["t"]), "price": list(ser["price"]), "plpc": list(ser["plpc"])}
                  for sym, ser in symbol_series.items()}

# --- Trailing detail: High-Water & Dynamic Stop por símbolo ---
trailing_detail = []
for tr in trailing_rows:
    sym = tr["symbol"]
    tpct = tr["trail_percent"]
    submitted = tr["submitted_at"]  # ISO
    high_water = None
    dyn_stop = None

    if sym in symbol_history and tpct is not None and submitted:
        tlist = symbol_history[sym]["t"]
        plist = symbol_history[sym]["price"]
        # encontrar índice desde el primer timestamp >= submitted
        start_idx = 0
        for i, ts in enumerate(tlist):
            if ts >= submitted:
                start_idx = i
                break
        if plist[start_idx:]:
            high_water = max(plist[start_idx:])
            dyn_stop = high_water * (1 - tpct / 100.0)

    trailing_detail.append({
        "symbol": sym,
        "trail_percent": tpct,
        "submitted_at": submitted,
        "high_water": d2(high_water) if high_water is not None else None,
        "dynamic_stop": d2(dyn_stop) if dyn_stop is not None else None
    })

# --- Protection por símbolo (para tabla y para columna en Positions) ---
protection_by_symbol = defaultdict(list)
for r in trailing_rows:
    label = f"Trailing {r['trail_percent']}%" if r['trail_percent'] is not None else "Trailing"
    protection_by_symbol[r["symbol"]].append(label)
for r in fixed_stop_rows:
    if r["stop_price"] is not None:
        protection_by_symbol[r["symbol"]].append(f"Stop ${r['stop_price']:.2f}")
    else:
        protection_by_symbol[r["symbol"]].append("Stop")

# --- Serializaciones JSON / HTML seguras ---
EQUITY_LABELS_INTRADAY_JSON = json.dumps(equity_labels_intraday)
EQUITY_VALUES_INTRADAY_JSON = json.dumps(equity_values_intraday)
EQUITY_LABELS_DAILY_JSON = json.dumps(equity_labels_daily)
EQUITY_VALUES_DAILY_JSON = json.dumps(equity_values_daily)
SYMBOL_HISTORY_JSON = json.dumps(symbol_history)

def prot_txt(sym):
    labs = protection_by_symbol.get(sym, [])
    return " · ".join(labs) if labs else "None"

POS_TBODY_HTML = "".join(
    f"<tr><td>{r['symbol']}</td>"
    f"<td>{r['qty']:.6g}</td>"
    f"<td>${r['avg_entry']:,.2f}</td>"
    f"<td>${r['current']:,.2f}</td>"
    f"<td>${r['market_value']:,.2f}</td>"
    f"<td class='{'pos' if r['unreal_pl']>=0 else 'neg'}'>${r['unreal_pl']:,.2f}</td>"
    f"<td class='{'pos' if r['unreal_plpc']>=0 else 'neg'}'>{r['unreal_plpc']*100:.2f}%</td>"
    f"<td>{prot_txt(r['symbol'])}</td></tr>"
    for r in pos_rows
)

ORD_TBODY_HTML = "".join(
    f"<tr><td class='muted'>{o['id']}</td>"
    f"<td>{o['symbol']}</td>"
    f"<td>{o['side']}</td>"
    f"<td>{o['type']}</td>"
    f"<td>{o['qty'] if o['qty'] is not None else ''}</td>"
    f"<td>{o['status']}</td>"
    f"<td>{o['submitted_at']}</td></tr>"
    for o in orders_rows
)

TRAIL_TBODY_HTML = "".join(
    f"<tr>"
    f"<td class='muted'>{o['id']}</td>"
    f"<td>{o['symbol']}</td>"
    f"<td>{o['qty'] if o['qty'] is not None else ''}</td>"
    f"<td>{(str(o['trail_percent'])+'%') if o['trail_percent'] is not None else ''}</td>"
    f"<td>{('$'+format(o['trail_price'],',.2f')) if o['trail_price'] is not None else ''}</td>"
    f"<td>{o['status']}</td>"
    f"<td>{o['submitted_at']}</td>"
    f"</tr>"
    for o in trailing_rows
)

STOP_TBODY_HTML = "".join(
    f"<tr>"
    f"<td class='muted'>{o['id']}</td>"
    f"<td>{o['symbol']}</td>"
    f"<td>{o['qty'] if o['qty'] is not None else ''}</td>"
    f"<td>{('$'+format(o['stop_price'],',.2f')) if o['stop_price'] is not None else ''}</td>"
    f"<td>{o['status']}</td>"
    f"<td>{o['submitted_at']}</td>"
    f"</tr>"
    for o in fixed_stop_rows
)

TRAIL_DETAIL_TBODY_HTML = "".join(
    f"<tr>"
    f"<td>{d['symbol']}</td>"
    f"<td>{(str(d['trail_percent'])+'%') if d['trail_percent'] is not None else ''}</td>"
    f"<td>{d['submitted_at']}</td>"
    f"<td>{('$'+format(d['high_water'],',.2f')) if d['high_water'] is not None else ''}</td>"
    f"<td>{('$'+format(d['dynamic_stop'],',.2f')) if d['dynamic_stop'] is not None else ''}</td>"
    f"</tr>"
    for d in trailing_detail
)

PORTFOLIO_VALUE_TXT = f"${portfolio_value:,.2f}"
LAST_EQUITY_TXT = f"${last_equity:,.2f}"
CASH_TXT = f"${cash:,.2f}"
BUYING_POWER_TXT = f"${buying_power:,.2f}"

# --- Template HTML (sin f-strings en HTML) ---
html_template = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Alpaca Paper Dashboard</title>
<style>
  :root {
    --bg: #0b0d10; --card: #111418; --muted: #9aa4ad; --fg: #e6eef5; --border: #222831;
    --pos: #14b86e; --neg: #ff5a5f; --accent: #60a5fa;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg:#f7f8fa; --card:#ffffff; --muted:#5b6670; --fg:#0b141a; --border:#dfe5ec;
      --pos:#0a7f4f; --neg:#c03a3e; --accent:#2563eb;
    }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; padding:16px; }
  .container{max-width:1200px;margin:0 auto}
  header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px;flex-wrap:wrap}
  h1{font-size:20px;margin:0}
  .muted{color:var(--muted)}
  .grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
  @media (max-width:900px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
  @media (max-width:560px){.grid{grid-template-columns:1fr}}
  .card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:12px}
  .kpi .label{font-size:12px;color:var(--muted);margin-bottom:6px}
  .kpi .value{font-size:22px;font-weight:600}
  .section-title{font-size:16px;margin:14px 0 6px 0}
  .tablewrap{overflow:auto;border:1px solid var(--border);border-radius:12px}
  table{border-collapse:separate;border-spacing:0;width:100%;min-width:760px;background:var(--card)}
  th,td{padding:10px 12px;border-bottom:1px solid var(--border);font-size:14px;text-align:right;white-space:nowrap}
  th:first-child,td:first-child{text-align:left}
  thead th{position:sticky;top:0;background:var(--card);z-index:1}
  tbody tr:hover{background:rgba(96,165,250,.08)}
  .pos{color:var(--pos)} .neg{color:var(--neg)}
  .row{display:grid;grid-template-columns:2fr 1fr;gap:12px}
  @media (max-width:900px){.row{grid-template-columns:1fr}}
  .toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  select,button{padding:8px 10px;border-radius:10px;border:1px solid var(--border);background:var(--card);color:var(--fg)}
  .foot{margin-top:12px;color:var(--muted);font-size:12px}
  .chartbox{height:320px}
  @media (max-width:560px){.chartbox{height:260px}}
</style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <h1>Alpaca Paper Dashboard</h1>
      <div class="muted">Last update: __TIMESTAMP__ (UTC)</div>
    </div>
    <div class="toolbar">
      <button id="equityToggle">Equity: Daily</button>
      <label class="muted" for="symSel" style="margin-left:8px">Symbol</label>
      <select id="symSel"></select>
      <button id="toggleMetric">Metric: % P/L</button>
    </div>
  </header>

  <div class="grid">
    <div class="card kpi"><div class="label">Portfolio Value</div><div class="value">__PORTFOLIO_VALUE__</div></div>
    <div class="card kpi"><div class="label">Last Equity (prev close)</div><div class="value">__LAST_EQUITY__</div></div>
    <div class="card kpi"><div class="label">Cash</div><div class="value">__CASH__</div></div>
    <div class="card kpi"><div class="label">Buying Power</div><div class="value">__BUYING_POWER__</div></div>
  </div>

  <div class="row">
    <div class="card">
      <div class="section-title">Equity History</div>
      <div class="chartbox"><canvas id="equityChart"></canvas></div>
      <div class="muted" style="font-size:12px;margin-top:6px">Default: Daily (one point per calendar day). Toggle to Intraday.</div>
    </div>
    <div class="card">
      <div class="section-title">Per-Symbol Performance</div>
      <div class="muted" style="font-size:13px;margin-bottom:6px">Switch between % P/L and Price</div>
      <div class="chartbox"><canvas id="symbolChart"></canvas></div>
    </div>
  </div>

  <div class="section-title">Active Trailing Stops</div>
  <div class="tablewrap">
    <table>
      <thead>
        <tr><th>ID</th><th>Symbol</th><th>Qty</th><th>Trail %</th><th>Trail $</th><th>Status</th><th>Submitted</th></tr>
      </thead>
      <tbody>
        __TRAIL_TBODY__
      </tbody>
    </table>
  </div>

  <div class="section-title">Trailing Detail (High-Water & Dynamic Stop)</div>
  <div class="tablewrap">
    <table>
      <thead>
        <tr><th>Symbol</th><th>Trail %</th><th>Submitted</th><th>High-Water</th><th>Dynamic Stop</th></tr>
      </thead>
      <tbody>
        __TRAIL_DETAIL_TBODY__
      </tbody>
    </table>
  </div>

  <div class="section-title">Active Fixed Stops</div>
  <div class="tablewrap">
    <table>
      <thead>
        <tr><th>ID</th><th>Symbol</th><th>Qty</th><th>Stop $</th><th>Status</th><th>Submitted</th></tr>
      </thead>
      <tbody>
        __STOP_TBODY__
      </tbody>
    </table>
  </div>

  <div class="section-title">Open Orders (All Types)</div>
  <div class="tablewrap">
    <table>
      <thead>
        <tr><th>ID</th><th>Symbol</th><th>Side</th><th>Type</th><th>Qty</th><th>Status</th><th>Submitted</th></tr>
      </thead>
      <tbody>
        __ORD_TBODY__
      </tbody>
    </table>
  </div>

  <div class="section-title">Positions</div>
  <div class="tablewrap">
    <table>
      <thead>
        <tr><th>Symbol</th><th>Qty</th><th>Avg Entry</th><th>Current</th><th>Market Value</th><th>Unreal P/L</th><th>Unreal P/L %</th><th>Protection</th></tr>
      </thead>
      <tbody>
        __POS_TBODY__
      </tbody>
    </table>
  </div>

  <div class="foot">Data: Alpaca Paper API · Static page updated by GitHub Actions · Mobile-friendly.</div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
const equityLabelsIntraday = __EQUITY_LABELS_INTRADAY_JSON__;
const equityValuesIntraday = __EQUITY_VALUES_INTRADAY_JSON__;
const equityLabelsDaily = __EQUITY_LABELS_DAILY_JSON__;
const equityValuesDaily = __EQUITY_VALUES_DAILY_JSON__;
const symbolHistory = __SYMBOL_HISTORY_JSON__;

const eqCtx = document.getElementById('equityChart').getContext('2d');
let equityMode = 'daily';
function buildEquityDataset() {
  if (equityMode === 'daily') return { labels: equityLabelsDaily, data: equityValuesDaily };
  return { labels: equityLabelsIntraday, data: equityValuesIntraday };
}
function renderEquity() {
  const ds = buildEquityDataset();
  if (window.eqChart) window.eqChart.destroy();
  window.eqChart = new Chart(eqCtx, {
    type: 'line',
    data: { labels: ds.labels, datasets: [{ label:'Portfolio Value', data: ds.data, borderWidth:2, fill:false, tension:0.25 }] },
    options: { responsive:true, maintainAspectRatio:false, plugins:{ legend:{display:false} },
      scales:{ y:{ ticks:{ callback:(v)=>'$'+v.toLocaleString() } } } }
  });
}
renderEquity();
document.getElementById('equityToggle').addEventListener('click', ()=>{
  equityMode = (equityMode === 'daily') ? 'intraday' : 'daily';
  document.getElementById('equityToggle').textContent = 'Equity: ' + (equityMode === 'daily' ? 'Daily' : 'Intraday');
  renderEquity();
});

// Per-symbol chart
const symSel = document.getElementById('symSel');
const toggleBtn = document.getElementById('toggleMetric');
let metric = 'plpc';
const symbols = Object.keys(symbolHistory).sort();
for (const s of symbols) { const opt = document.createElement('option'); opt.value = s; opt.textContent = s; symSel.appendChild(opt); }
if (symbols.length === 0) { const opt = document.createElement('option'); opt.value=''; opt.textContent='No positions'; symSel.appendChild(opt); }
const symCtx = document.getElementById('symbolChart').getContext('2d');
let symChart = null;
function renderSymbolChart(sym) {
  if (!sym || !symbolHistory[sym]) return;
  const H = symbolHistory[sym]; const labels = H.t; const data = (metric === 'plpc') ? H.plpc : H.price; const label = (metric === 'plpc') ? '% P/L' : 'Price';
  if (symChart) symChart.destroy();
  symChart = new Chart(symCtx, {
    type:'line',
    data:{ labels, datasets:[{ label: sym+' '+label, data, borderWidth:2, fill:false, tension:0.25 }] },
    options:{ responsive:true, maintainAspectRatio:false, plugins:{ legend:{display:false} },
      scales:{ y:{ ticks:{ callback:(v)=> metric==='plpc' ? v.toFixed(2)+'%' : '$'+v.toLocaleString() } } } }
  });
}
symSel.addEventListener('change', ()=> renderSymbolChart(symSel.value));
toggleBtn.addEventListener('click', ()=>{
  metric = (metric === 'plpc') ? 'price' : 'plpc';
  toggleBtn.textContent = 'Metric: ' + (metric === 'plpc' ? '% P/L' : 'Price');
  renderSymbolChart(symSel.value);
});
if (symbols.length > 0) { symSel.value = symbols[0]; renderSymbolChart(symbols[0]); }
</script>
</body>
</html>
"""

# --- Reemplazos de tokens ---
html = (html_template
    .replace("__TIMESTAMP__", timestamp)
    .replace("__PORTFOLIO_VALUE__", PORTFOLIO_VALUE_TXT)
    .replace("__LAST_EQUITY__", LAST_EQUITY_TXT)
    .replace("__CASH__", CASH_TXT)
    .replace("__BUYING_POWER__", BUYING_POWER_TXT)
    .replace("__EQUITY_LABELS_INTRADAY_JSON__", json.dumps(equity_labels_intraday))
    .replace("__EQUITY_VALUES_INTRADAY_JSON__", json.dumps(equity_values_intraday))
    .replace("__EQUITY_LABELS_DAILY_JSON__", json.dumps(equity_labels_daily))
    .replace("__EQUITY_VALUES_DAILY_JSON__", json.dumps(equity_values_daily))
    .replace("__SYMBOL_HISTORY_JSON__", json.dumps(symbol_history))
    .replace("__ORD_TBODY__", ORD_TBODY_HTML)
    .replace("__TRAIL_TBODY__", TRAIL_TBODY_HTML)
    .replace("__STOP_TBODY__", STOP_TBODY_HTML)
    .replace("__TRAIL_DETAIL_TBODY__", TRAIL_DETAIL_TBODY_HTML)
    .replace("__POS_TBODY__", POS_TBODY_HTML)
)

OUT_HTML.write_text(html, encoding="utf-8")
print(f"Wrote {OUT_HTML} (with trailing detail) and updated {HIST_EQUITY} / {HIST_POS}")
