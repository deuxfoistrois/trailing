# manage_stops.py — STOP -10% inicial, swap a TRAILING -8% cuando PL% >= +5%
import os
from decimal import Decimal, ROUND_HALF_UP
from math import floor
from time import sleep

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest, StopOrderRequest, TrailingStopOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType, QueryOrderStatus

# ====== Parámetros ======
ACTIVACION_MIN_GANANCIA = 0.05   # +5% → activar trailing
TRAIL_PERCENT = 8.0              # trailing 8%
STOP_LOSS_PORCENTAJE = 0.10      # stop fijo -10% (desde avg_entry)
ROUND_DOWN_TRAILING_QTY_TO_INT = True  # Alpaca NO permite trailing con fracciones
POST_CANCEL_SLEEP_SECS = 1.0     # espera breve tras cancelar STOP para liberar qty
CERRAR_SOLO_LARGOS = True

# ====== Conexión (paper) ======
API_KEY = os.environ["APCA_API_KEY_ID"]
API_SECRET = os.environ["APCA_API_SECRET_KEY"]
client = TradingClient(API_KEY, API_SECRET, paper=True)

# ====== Helpers ======
def _round2(x: float) -> float:
    return float(Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def es_fraccional(qty: float) -> bool:
    return int(qty) != qty

def tif_para_stop(qty: float) -> TimeInForce:
    # Regla Alpaca: fraccional => DAY; entero => GTC
    return TimeInForce.DAY if es_fraccional(qty) else TimeInForce.GTC

def ordenes_abiertas_symbol(symbol: str):
    req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
    return list(client.get_orders(filter=req))

def get_open_stop(symbol: str):
    for o in ordenes_abiertas_symbol(symbol):
        if o.side == OrderSide.SELL and o.type == OrderType.STOP:
            return o
    return None

def get_open_trailing(symbol: str):
    for o in ordenes_abiertas_symbol(symbol):
        if o.side == OrderSide.SELL and o.type == OrderType.TRAILING_STOP:
            return o
    return None

def cancelar(order_id: str):
    client.cancel_order_by_id(order_id)

# ====== Envío de órdenes ======
def enviar_stop(symbol: str, qty: float, stop_price: float):
    tif = tif_para_stop(qty)
    req = StopOrderRequest(
        symbol=symbol,
        side=OrderSide.SELL,
        qty=qty,
        stop_price=_round2(stop_price),
        time_in_force=tif,
    )
    resp = client.submit_order(order_data=req)
    print(f"[STOP] {symbol} qty={qty} tif={tif.value} stop=${_round2(stop_price):.2f} id={resp.id}")
    return resp.id

def enviar_trailing(symbol: str, qty: float, trail_percent: float):
    q = qty
    if es_fraccional(q):
        if not ROUND_DOWN_TRAILING_QTY_TO_INT:
            raise ValueError("Trailing no permitido con qty fraccional")
        q = float(floor(q))
        if q <= 0:
            raise ValueError("Qty entera=0; no se puede enviar trailing")
    req = TrailingStopOrderRequest(
        symbol=symbol,
        side=OrderSide.SELL,
        qty=q,
        time_in_force=TimeInForce.GTC,   # permitido para qty entera
        trail_percent=trail_percent,
    )
    resp = client.submit_order(order_data=req)
    print(f"[TRAIL] {symbol} qty={q} tif=gtc trail%={trail_percent} id={resp.id}")
    return resp.id

# ====== Main ======
def main():
    try:
        acc = client.get_account()
        print(f"Cuenta: last_equity=${float(acc.last_equity) if acc.last_equity else 0.0:,.2f}")
    except Exception:
        print("Cuenta: no se pudo leer last_equity.")

    posiciones = client.get_all_positions()
    nuevas = 0

    for p in posiciones:
        qty_total = float(p.qty)
        if CERRAR_SOLO_LARGOS and qty_total <= 0:
            continue

        symbol = p.symbol
        avg = float(p.avg_entry_price)
        last = float(p.current_price)
        plpc = float(p.unrealized_plpc) if p.unrealized_plpc is not None else None  # 0.07 = +7%
        stop_target = avg * (1 - STOP_LOSS_PORCENTAJE)

        pl_txt = f"{plpc*100:.2f}%" if plpc is not None else "N/D"
        print(f"\n{symbol}: qty={qty_total} avg=${avg:.2f} last=${last:.2f} PL%={pl_txt}")

        open_stop = get_open_stop(symbol)
        open_tr = get_open_trailing(symbol)

        # Caso 1: ya hay trailing → asegurarnos de no dejar stop duplicado
        if open_tr:
            if open_stop:
                try:
                    cancelar(open_stop.id)
                    print(f"  - STOP redundante cancelado (id={open_stop.id})")
                except Exception as e:
                    print(f"  - No se pudo cancelar STOP redundante → {e}")
            print("  - Trailing ya activo. Nada más que hacer.")
            continue

        # Caso 2: PL% >= +5% → SWAP STOP→TRAILING
        if plpc is not None and plpc >= ACTIVACION_MIN_GANANCIA:
            # liberar qty: cancelar STOP si existe
            if open_stop:
                try:
                    cancelar(open_stop.id)
                    print(f"  - STOP cancelado para swap (id={open_stop.id})")
                    sleep(POST_CANCEL_SLEEP_SECS)
                except Exception as e:
                    print(f"  - No se pudo cancelar STOP previo → {e}")
                    # si no cancela, no intentamos trailing para evitar 422 qty
                    continue
            # enviar trailing
            try:
                enviar_trailing(symbol, qty_total, TRAIL_PERCENT)
                nuevas += 1
            except Exception as e:
                print(f"  - Error al enviar TRAILING → {e}")
                # rollback: recrear STOP para no dejar sin protección
                try:
                    enviar_stop(symbol, qty_total, stop_target)
                    print("  - Rollback: STOP recreado tras fallo de trailing.")
                except Exception as e2:
                    print(f"  - Falló también recrear STOP → {e2}")
            continue

        # Caso 3: PL% < +5% → asegurar STOP -10% (si no existe)
        if not open_stop:
            try:
                enviar_stop(symbol, qty_total, stop_target)
                nuevas += 1
            except Exception as e:
                print(f"  - Error al enviar STOP → {e}")
        else:
            print(f"  - STOP ya presente (id={open_stop.id})")

    print(f"\nTotal órdenes nuevas: {nuevas}")

if __name__ == "__main__":
    main()
