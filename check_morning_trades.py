import sqlite3
import os
from get_setting import get_base_path

base_path = get_base_path()
db_path = os.path.join(base_path, 'LogData', 'kipostock_data.db')

if not os.path.exists(db_path):
    print(f"❌ DB file not found: {db_path}")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades WHERE strat_mode LIKE 'MORNING%'")
    rows = cursor.fetchall()
    if rows:
        print(f"✅ Found {len(rows)} Morning Betting trades:")
        for row in rows:
            print(row)
    else:
        print("❌ No Morning Betting trades found in database.")
    conn.close()
