import os, json, csv, pathlib, datetime
from decimal import Decimal
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

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
HIST = DATA / "equity_history.csv"
OUT_HTML = DOCS / "index.html"

# --- Utilidades ---
def d2(x):
    return float(Decimal(str(x)).quantize(Decimal("0.01")))

def now_iso():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

# --- Datos de cuenta/posiciones/ordenes ---
account = client.get_account()
positions = client.get_all_positions()
open_orders = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))

timestamp = now_iso()
portfolio_value = float(account.portfolio_value)  # valor tiempo-real
cash = float(account.cash)
buying_power = float(account.buying_power)
last_equity = float(account.last_equity) if account.last_equity is not None else portfolio_value

# --- Actualizar historial de equity ---
new_row = [timestamp, f"{portfolio_value:.2f}", f"{last_equity:.2f}", f"{cash:.2f}", f"{buying_power:.2f}"]
write_header = not HIST.exists()
append = True
if HIST.exists():
    try:
        with HIST.open("r", newline="") as f:
            rows = list(csv.reader(f))
            if rows and rows[-1] and rows[-1][0] == timestamp:
                append = False
    except Exception:
        pass

if append:
    with HIST.open("a", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["timestamp","portfolio_value","last_equity","cash","buying_power"])
        w.writerow(new_row)

# --- Preparar datos para HTML ---
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

orders_rows = []
for o in open_orders:
    orders_rows.append({
        "id": o.id,
        "symbol": o.symbol,
        "side": o.side.value,
        "type": o.type.value,
        "qty": float(o.qty) if hasattr(o, "qty") and o.qty is not None else None,
        "status": o.status.value,
        "submitted_at": o.submitted_at.isoformat() if o.submitted_at else "",
    })

# Cargar historial para el gráfico
hist_labels, hist_values = [], []
if HIST.exists():
    with HIST.open("r", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            hist_labels.append(row["timestamp"])
            hist_values.append(float(row["portfolio_value"]))

# --- HTML (estático) ---
html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Alpaca Paper Dashboard</title>
<style>
  body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 24px; }}
  h1 {{ margin: 0 0 8px; }}
  .meta {{ margin-bottom: 16px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px; font-size: 14px; text-align: right; }}
  th {{ background: #f6f6f6; text-align: right; }}
  th:first-child, td:first-child {{ text-align: left; }}
  .pos {{ overflow-x:auto; }}
  .pill {{ display:inline-block; padding:2px 8px; border-radius: 12px; border:1px solid #ccc; font-size:12px; }}
  .green {{ color:#0a0; }}
  .red {{ color:#a00; }}
  .grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(220px,1fr)); gap: 12px; margin: 16px 0; }}
  .card {{ border:1px solid #ddd; border-radius:8px; padding:12px; }}
  .muted {{ color:#666; }}
  canvas {{ max-width: 100%; height: 320px; }}
</style>
</head>
<body>

<h1>Alpaca Paper Dashboard</h1>
<div class="meta muted">Last update: {timestamp} (UTC)</div>

<div class="grid">
  <div class="card"><div class="muted">Portfolio Value</div><div style="font-size:22px;">${portfolio_value:,.2f}</div></div>
  <div class="card"><div class="muted">Last Equity (prev close)</div><div style="font-size:22px;">${last_equity:,.2f}</div></div>
  <div class="card"><div class="muted">Cash</div><div style="font-size:22px;">${cash:,.2f}</div></div>
  <div class="card"><div class="muted">Buying Power</div><div style="font-size:22px;">${buying_power:,.2f}</div></div>
</div>

<h2>Equity History</h2>
<canvas id="equityChart"></canvas>

<h2>Positions</h2>
<div class="pos">
<table>
  <thead>
    <tr>
      <th>Symbol</th><th>Qty</th><th>Avg Entry</th><th>Current</th><th>Market Value</th><th>Unreal P/L</th><th>Unreal P/L %</th>
    </tr>
  </thead>
  <tbody>
    {''.join(f"<tr><td>{r['symbol']}</td><td>{r['qty']:.6g}</td><td>${r['avg_entry']:,.2f}</td><td>${r['current']:,.2f}</td><td>${r['market_value']:,.2f}</td><td class='{'green' if r['unreal_pl']>=0 else 'red'}'>${r['unreal_pl']:,.2f}</td><td class='{'green' if r['unreal_plpc']>=0 else 'red'}'>{r['unreal_plpc']*100:.2f}%</td></tr>" for r in pos_rows)}
  </tbody>
</table>
</div>

<h2>Open Orders</h2>
<div class="pos">
<table>
  <thead>
    <tr><th>ID</th><th>Symbol</th><th>Side</th><th>Type</th><th>Qty</th><th>Status</th><th>Submitted</th></tr>
  </thead>
  <tbody>
    {''.join(f"<tr><td class='muted'>{o['id']}</td><td>{o['symbol']}</td><td>{o['side']}</td><td>{o['type']}</td><td>{o['qty'] if o['qty'] is not None else ''}</td><td>{o['status']}</td><td>{o['submitted_at']}</td></tr>" for o in orders_rows)}
  </tbody>
</table>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
const labels = {json.dumps(hist_labels)};
const data = {json.dumps(hist_values)};
const ctx = document.getElementById('equityChart').getContext('2d');
new Chart(ctx, {{
  type: 'line',
  data: {{
    labels,
    datasets: [{{
      label: 'Portfolio Value',
      data: data,
      borderWidth: 2,
      fill: false,
      tension: 0.1
    }}]
  }},
  options: {{
    responsive: true,
    scales: {{
      y: {{
        ticks: {{
          callback: (v) => '$' + v.toLocaleString()
        }}
      }}
    }},
    plugins: {{
      legend: {{ display: false }}
    }}
  }}
}});
</script>

</body>
</html>
"""

OUT_HTML.write_text(html, encoding="utf-8")
print(f"Wrote {OUT_HTML} and updated {HIST}")
