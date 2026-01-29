try:
    import PyQt6
    print("PyQt6 OK")
    import requests
    print("requests OK")
    import websockets
    print("websockets OK")
    import pandas
    print("pandas OK") # Request was removed but let's check general health
except ImportError as e:
    print(f"Import ERROR: {e}")
except Exception as e:
    print(f"General ERROR: {e}")
