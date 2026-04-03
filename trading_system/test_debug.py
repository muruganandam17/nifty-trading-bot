import requests,pandas as pd
from datetime import datetime
UA = "Mozilla/5.0"
url = "https://query1.finance.yahoo.com/v8/finance/chart/^NSEI?range=30d&interval=5m"
r = requests.get(url, headers={"User-Agent":UA}, timeout=15)
d = r.json()
res = d["chart"]["result"][0]
ts = res.get("timestamp",[])
print("Total candles:", len(ts))
print("First ts:", ts[0])
print("Last ts:", ts[-1])
print("First time:", datetime.fromtimestamp(ts[0]))
print("Last time:", datetime.fromtimestamp(ts[-1]))
