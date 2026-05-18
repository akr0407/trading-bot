"""
Verify MT5Bridge connects using the correct display server name.
"""
import sys, os
if sys.platform == 'win32':
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridges.mt5_bridge import MT5Bridge

bridge = MT5Bridge(
    login=61248357,
    password="Ab0,i(fa",
    server="FinexBisnisSolusi-Demo",   # display name, NOT hostname
)

print("Connecting with server='FinexBisnisSolusi-Demo'...")
connected = bridge.connect()
if connected:
    bal = bridge.get_balance()
    print(f"SUCCESS - Balance: {bal['balance']} {bal['currency']}")
    bridge.disconnect()
else:
    import MetaTrader5 as mt5
    print(f"FAILED - {mt5.last_error()}")
    mt5.shutdown()
