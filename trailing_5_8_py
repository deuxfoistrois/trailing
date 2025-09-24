import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import TrailingStopOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType, QueryOrderStatus

# Lee claves desde GitHub Secrets (ENV)
API_KEY = os.environ["APCA_API_KEY_ID"]
API_SECRET = os.environ["APCA_API_SECRET_KEY"]

# Cliente apuntando a PAPER
client = TradingClient(API_KEY, API_SECRET, paper=True)

# Parámetros de estrategia
ACTIVACION_MIN_GANANCIA = 0.05   # 5% de ganancia para activar
TRAIL_PERCENT = 8.0              # trailing 8% desde el máximo (HWM)
CERRAR_SOLO_LARGOS = True        # limitar a posiciones largas

def tiene_trailing_abierto(symbol: str) -> bool:
    req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
    for o in client.get_orders(filter=req):
        if o.type == OrderType.TRAILING_STOP and o.side == OrderSide.SELL:
            return True
    return False

def run():
    posiciones = client.get_all_positions()
    acciones = 0
    for p in posiciones:
        # Filtra largos si corresponde
        if CERRAR_SOLO_LARGOS and float(p.qty) <= 0:
            continue

        # unrealized_plpc: 0.05 = +5%
        try:
            plpc = float(p.unrealized_plpc)
        except Exception:
            continue

        if plpc >= ACTIVACION_MIN_GANANCIA and not tiene_trailing_abierto(p.symbol):
            qty = float(p.qty)  # cierra todo
            orden = TrailingStopOrderRequest(
                symbol=p.symbol,
                side=OrderSide.SELL,
                qty=qty,
                time_in_force=TimeInForce.GTC,
                trail_percent=TRAIL_PERCENT
            )
            resp = client.submit_order(order_data=orden)
            print(f"ENVIADO {p.symbol} qty={qty} trail%={TRAIL_PERCENT} id={resp.id}")
            acciones += 1
        else:
            print(f"OK {p.symbol} sin acción (PL%={plpc*100:.2f} / trailing_abierto={tiene_trailing_abierto(p.symbol)})")
    print(f"Total órdenes nuevas: {acciones}")

if __name__ == "__main__":
    run()
