import os
BASE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(BASE, 'vendor')
DATA = os.path.join(BASE, 'data')
KEYS = os.path.join(BASE, 'keys')
#!/usr/bin/env python3
import csv
import json
import re
import subprocess
from collections import Counter, defaultdict

ASSETS = DATA
HIST = os.path.join(DATA, 'hkia_gate_history.csv')
TYPES_PATH = os.path.join(DATA, 'flight_types.json')

try:
    store = json.load(open(TYPES_PATH))
except Exception:
    store = {}

fa = defaultdict(Counter)
for r in csv.DictReader(open(HIST)):
    f = r["flight_no"].replace(" ", "")
    if f:
        fa[f][r["airline"]] += 1

def grab(url):
    out = subprocess.run(["curl", "-s", "--max-time", "30", url],
                         capture_output=True, text=True, timeout=60).stdout
    try:
        d = json.loads(out)
        return d.get("ac") or d.get("aircraft") or []
    except Exception:
        return []

ac = grab("https://api.adsb.lol/v2/point/22.309/113.915/250")
if len(ac) < 20:
    ac = ac + grab("https://opendata.adsb.fi/api/v2/lat/22.309/lon/113.915/dist/250")
if len(ac) < 20:
    ac = ac + grab("https://api.airplanes.live/v2/point/22.309/113.915/250")

snap = {}
for a in ac:
    fl = (a.get("flight") or "").strip()
    if fl and a.get("t"):
        snap[fl] = a

matched = 0
for f, cnt in fa.items():
    icao = cnt.most_common(1)[0][0]
    digits = re.sub(r"\D", "", f)
    a = snap.get(icao + digits)
    if not a:
        continue
    t = a["t"]
    reg = a.get("r", "")
    e = store.setdefault(f, {"t": {}, "r": {}})
    e["t"][t] = e["t"].get(t, 0) + 1
    if reg:
        e["r"][reg] = e["r"].get(reg, 0) + 1
    matched += 1

json.dump(store, open(TYPES_PATH, "w"))

agg = Counter()
for e in store.values():
    for t, n in e["t"].items():
        agg[t] += n
print(f"snapshot: {len(snap)} typed aircraft airborne | matched: {matched}/{len(fa)} flights | store: {len(store)} flights typed")
print("top types at HKG so far:", agg.most_common(10))
