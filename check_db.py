import sqlite3
import os

db_path = r'D:\Work\Python\AutoBuy\ExeFile\KipoStockAi\LogData\kipostock_data.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
    if c.fetchone():
        c.execute("SELECT trade_date, code, name, strat_mode FROM trades WHERE strat_mode LIKE 'MORNING%'")
        rows = c.fetchall()
        print(f"Found {len(rows)} MORNING trades.")
        for r in rows:
            print(r)
    else:
        print("Table 'trades' does not exist.")
    conn.close()
else:
    print(f"DB not found at {db_path}")
