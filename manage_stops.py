import os
from decimal import Decimal, ROUND_HALF_UP

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    GetOrdersRequest,
    StopOrderRequest,
    TrailingStopOrderRequest,
)
from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
    OrderType,
    QueryOrderStatus,
)

# ===== Parámetros =====
ACTIVACION_MIN_GANANCIA = 0.05     # 5%: cuando >= +5% coloca trailing
TRAIL_PERCENT = 8.0                # trailing 8%
STOP_LOSS_PORCENTAJE = 0.10        # stop loss fijo -10%
CERRAR_SOLO_LARGOS = True
CANCELAR_STOP_FIJO_AL_PONER_TRAILING = True  # recomendado

# ===== Conexión (paper) =====
API_KEY = os.environ["APCA_API_KEY_ID"]
API_SECRET = os.environ["APCA_API_SECRET_KEY"]
client = TradingClient(API_KEY, API_SECRET, paper=True)

def _round2(x: float) -> float:
    # Redondeo a 2 decimales típico de equities
    return float(Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def _ordenes_abiertas_symbol(symbol: str):
    req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
    return list(client.get_orders(filter=req))

def tiene_trailing(symbol: str) -> bool:
    for o in _ordenes_abiertas_symbol(symbol):
        if o.side == OrderSide.SELL and o.type == OrderType.TRAILING_STOP:
            return True
    return False

def id_stop_fijo(symbol: str):
    for o in _ordenes_abiertas_symbol(symbol):
        if o.side == OrderSide.SELL and o.type == OrderType.STOP:
            return o.id
    return None

def enviar_stop_fijo(symbol: str, qty: float, stop_price: float):
    stop_req = StopOrderRequest(
        symbol=symbol,
        side=OrderSide.SELL,
        qty=qty,
        stop_price=_round2(stop_price),
        time_in_force=TimeInForce.GTC,
    )
    resp = client.submit_order(order_data=stop_req)
    print(f"STOP FIJO enviado: {symbol} qty={qty} stop={_round2(stop_price)} id={resp.id}")

def enviar_trailing(symbol: str, qty: float, trail_percent: float):
    tr_req = TrailingStopOrderRequest(
        symbol=symbol,
        side=OrderSide.SELL,
        qty=qty,
        time_in_force=TimeInForce.GTC,
        trail_percent=trail_percent,
    )
    resp = client.submit_order(order_data=tr_req)
    print(f"TRAILING enviado: {symbol} qty={qty} trail%={trail_percent} id={resp.id}")
    return resp.id

def cancelar_orden(order_id: str):
    try:
        client.cancel_order_by_id(order_id)
        print(f"Orden cancelada: {order_id}")
    except Exception as e:
        print(f"No se pudo cancelar {order_id}: {e}")

def main():
    posiciones = client.get_all_positions()
    nuevas_ordenes = 0

    for p in posiciones:
        qty = float(p.qty)
        if CERRAR_SOLO_LARGOS and qty <= 0:
            continue

        symbol = p.symbol
        avg_entry = float(p.avg_entry_price)
        stop_price = avg_entry * (1 - STOP_LOSS_PORCENTAJE)

        # 1) STOP LOSS FIJO (-10%) si no existe
        stop_id = id_stop_fijo(symbol)
        if stop_id is None:
            enviar_stop_fijo(symbol, qty, stop_price)
            nuevas_ordenes += 1
        else:
            print(f"{symbol}: stop fijo ya existe (id={stop_id})")

        # 2) TRAILING (-8%) si PL% >= +5% y aún no hay trailing
        try:
            plpc = float(p.unrealized_plpc)  # 0.05 = +5%
        except Exception:
            plpc = None

        if plpc is not None and plpc >= ACTIVACION_MIN_GANANCIA:
            if not tiene_trailing(symbol):
                tr_id = enviar_trailing(symbol, qty, TRAIL_PERCENT)
                nuevas_ordenes += 1
                # (Opcional) cancelar el stop fijo al activar trailing
                if CANCELAR_STOP_FIJO_AL_PONER_TRAILING:
                    stop_id = id_stop_fijo(symbol)
                    if stop_id:
                        cancelar_orden(stop_id)
            else:
                print(f"{symbol}: trailing ya existe.")
        else:
            print(f"{symbol}: PL%={plpc*100:.2f}% < {ACTIVACION_MIN_GANANCIA*100:.0f}% → sin trailing.")

    print(f"Total órdenes nuevas: {nuevas_ordenes}")

if __name__ == "__main__":
    main()
