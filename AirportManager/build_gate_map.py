import os
BASE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(BASE, 'vendor')
DATA = os.path.join(BASE, 'data')
KEYS = os.path.join(BASE, 'keys')
#!/usr/bin/env python3
import csv
import json
import subprocess
import time
from collections import Counter, defaultdict
from datetime import date

from shapely.geometry import Polygon as ShPoly
from shapely.ops import unary_union

HIST = os.path.join(DATA, 'hkia_gate_history.csv')
COORDS_CSV = os.path.join(DATA, 'vhhh_gates.csv')
AIRLINES_CACHE = os.path.join(BASE, 'hkia_airlines.json')
ASSETS = DATA
OUT = os.path.join(BASE, "vhhh_gate_map.html")

KEEP_BUILDINGS = {"terminal", "hangar", "yes", "industrial", "commercial",
                  "transportation", "service", "warehouse", "fire_station",
                  "train_station"}

BBOX = (22.275, 113.875, 22.35, 113.97)
M = 0.002


def in_b(p):
    return BBOX[0] - M <= p[1] <= BBOX[2] + M and BBOX[1] - M <= p[0] <= BBOX[3] + M


def build_geo():
    raw = json.load(open(os.path.join(VENDOR, 'vhhh_geometry.json')))
    feats = []
    extra_labels = {}
    for e in raw.get("elements", []):
        tags = e.get("tags", {})
        name = tags.get("name:en") or tags.get("name") or ""
        if "aeroway" in tags:
            k = tags["aeroway"]
        elif tags.get("building") == "construction" and "T2 Concourse" in name:
            k = "construction"
        elif tags.get("building") in KEEP_BUILDINGS:
            k = "building"
        else:
            continue
        geom = e.get("geometry") or []
        allpts = [[round(p["lon"], 5), round(p["lat"], 5)] for p in geom]
        if len(allpts) < 2:
            continue
        ins = [in_b(p) for p in allpts]
        ref = tags.get("ref", "")
        if k in ("runway", "taxiway"):
            cur = []
            for pt, ok in zip(allpts, ins):
                if ok:
                    cur.append(pt)
                else:
                    if len(cur) >= 2:
                        feats.append({"type": "Feature",
                                      "properties": {"k": k, "name": name, "ref": ref},
                                      "geometry": {"type": "LineString", "coordinates": cur}})
                        cur = []
            if len(cur) >= 2:
                feats.append({"type": "Feature",
                              "properties": {"k": k, "name": name, "ref": ref},
                              "geometry": {"type": "LineString", "coordinates": cur}})
            continue
        if not all(ins):
            continue
        pts = allpts
        if pts[0] == pts[-1]:
            coords = [pts[:-1]]
            if len(coords[0]) < 3:
                continue
            f = {"type": "Polygon", "coordinates": coords}
        else:
            f = {"type": "LineString", "coordinates": pts}
        h = 0
        try:
            h = float(tags.get("height") or 0)
        except (TypeError, ValueError):
            h = 0
        if not h:
            try:
                h = float(tags.get("building:levels") or 0) * 3.3
            except (TypeError, ValueError):
                h = 0
        feats.append({"type": "Feature", "properties": {"k": k, "name": name, "h": round(h, 1)}, "geometry": f})
        if k in ("terminal", "construction") and name:
            la = sum(p[1] for p in pts) / len(pts)
            lo = sum(p[0] for p in pts) / len(pts)
            label = "T2 Concourse (u/c)" if k == "construction" else name
            extra_labels[label] = (round(la, 5), round(lo, 5))
    return {"type": "FeatureCollection", "features": feats}, extra_labels

coords = {}
for r in csv.DictReader(open(COORDS_CSV)):
    coords[r["gate"]] = (float(r["lat"]), float(r["lon"]))

try:
    airlines = json.load(open(AIRLINES_CACHE))
except Exception:
    raw = subprocess.run(
        ["curl", "-s", "--max-time", "40", "-A", "Mozilla/5.0",
         "https://www.hongkongairport.com/flightinfo-rest/rest/airlines"],
        capture_output=True, text=True, timeout=60).stdout
    airlines = json.loads(raw)
    json.dump(airlines, open(AIRLINES_CACHE, "w"))
airnames = {a["code"]: a["description"][0] for a in airlines}

combos = {k: {"gt": Counter(), "ag": defaultdict(Counter), "ga": defaultdict(Counter),
              "fl": defaultdict(Counter), "fa": defaultdict(Counter)}
          for k in ["D-pax", "A-pax", "D-cargo", "A-cargo"]}
dates = set()
nrec = 0
for r in csv.DictReader(open(HIST)):
    if not r["gate"]:
        continue
    nrec += 1
    dates.add(r["date"])
    c = combos[f"{r['direction']}-{'cargo' if r['cargo'] == 'Y' else 'pax'}"]
    g, a, f = r["gate"], r["airline"], r["flight_no"].replace(" ", "")
    c["gt"][g] += 1
    c["ag"][g][a] += 1
    c["ga"][a][g] += 1
    c["fl"][f][g] += 1
    c["fa"][f][a] += 1

def prune(c):
    fl = {}
    for f, gc in c["fl"].items():
        if sum(gc.values()) >= 3:
            fl[f] = {"a": c["fa"][f].most_common(1)[0][0], "g": dict(gc.most_common(6))}
    return {
        "gt": dict(c["gt"]),
        "ag": {g: dict(ac.most_common(10)) for g, ac in c["ag"].items()},
        "ga": {a: dict(gc) for a, gc in c["ga"].items()},
        "fl": fl,
    }

def centroid(gates):
    pts = [coords[g] for g in gates if g in coords]
    if not pts:
        return None
    return (round(sum(p[0] for p in pts) / len(pts), 5),
            round(sum(p[1] for p in pts) / len(pts), 5))

labels = {
    "T1 Main": centroid([str(i) for i in range(1, 13)] + ["23", "24", "25", "26"]),
    "T1 Satellite (13-21)": centroid([str(i) for i in range(13, 22)]),
    "Central (23-36)": centroid([str(i) for i in range(23, 37)]),
    "SW Pier (40-50)": centroid([str(i) for i in range(40, 51)]),
    "NW Pier (60-71)": centroid([str(i) for i in range(60, 72)]),
    "Midfield (201-230)": centroid([str(i) for i in range(201, 231)]),
    "Remote stands (5xx)": centroid([str(i) for i in range(511, 526)]),
}
geo, geo_labels = build_geo()
for k, v in geo_labels.items():
    if k not in ("Terminal 1", "T1 Satellite Concourse", "T1 Midfield Concourse"):
        labels.setdefault(k, v)

def area_of(g):
    try:
        n = int(g)
    except ValueError:
        return "?"
    if n <= 12:
        return "T1 north"
    if n <= 21:
        return "T1 Satellite"
    if n <= 36:
        return "Central concourse"
    if n <= 50:
        return "SW pier"
    if n <= 71:
        return "NW pier"
    if 200 <= n <= 230:
        return "Midfield"
    if n >= 500:
        return "Remote/bus"
    return "?"

def live_snapshot():
    day = date.today().isoformat()
    url = f"https://www.hongkongairport.com/flightinfo-rest/rest/flights?span=2&date={day}&lang=en"
    try:
        out = subprocess.run(["curl", "-s", "--max-time", "40", "-A", "Mozilla/5.0", url],
                             capture_output=True, text=True, timeout=60).stdout
        groups = json.loads(out)
    except Exception:
        return {"ts": 0, "rows": []}
    rows = []
    for g in groups if isinstance(groups, list) else []:
        if g.get("cargo"):
            continue
        d = "A" if g.get("arrival") else "D"
        for rec in g.get("list", []):
            for f in rec.get("flight", []):
                rows.append({"date": g.get("date", ""), "dir": d, "f": f.get("no", "").replace(" ", ""),
                             "gate": rec.get("gate", ""), "time": rec.get("time", ""),
                             "status": rec.get("status", ""),
                             "dest": "|".join(rec.get("destination") or rec.get("origin") or []),
                             "terminal": rec.get("terminal", ""), "aisle": rec.get("aisle", "")})
    return {"ts": time.time(), "rows": rows}

try:
    aps = json.load(open(os.path.join(DATA, 'hkia_airports.json')))
except Exception:
    raw = subprocess.run(
        ["curl", "-s", "--max-time", "40", "-A", "Mozilla/5.0",
         "https://www.hongkongairport.com/flightinfo-rest/rest/airports"],
        capture_output=True, text=True, timeout=60).stdout
    aps = json.loads(raw)
    json.dump(aps, open(os.path.join(DATA, 'hkia_airports.json'), "w"))
AIRPORTS = {a["code"]: a["description"][0].upper()
            for a in aps
            if a.get("code") and a.get("description") and "testing" not in a["description"][0].lower()}

try:
    tstore = json.load(open(os.path.join(DATA, 'flight_types.json')))
except Exception:
    tstore = {}
TYPES = {}
REGS = {}
for f, e in tstore.items():
    if e.get("t"):
        TYPES[f] = max(e["t"], key=e["t"].get)
    if e.get("r"):
        REGS[f] = max(e["r"], key=e["r"].get)

TAXI_GRAPH = json.load(open(os.path.join(DATA, 'taxi_graph.json')))
TAXI_STATS = json.load(open(os.path.join(DATA, 'taxi_stats.json')))

cs_dest = defaultdict(Counter)
for r in csv.DictReader(open(HIST)):
    f = r["flight_no"].replace(" ", "")
    d0 = (r["destination"] or "").split("|")[0]
    if f and d0 and r["direction"] == "D" and r["cargo"] == "N":
        cs_dest[f][d0] += 1
CSROUTES = {}
for f, c in cs_dest.items():
    top = c.most_common(1)[0][0]
    if top in AIRPORTS:
        CSROUTES[f] = AIRPORTS[top]

def build_geo3d():
    aprons, buildings, rwy, twy = [], [], [], []
    for f in geo["features"]:
        k = f["properties"]["k"]
        g = f["geometry"]
        if k == "runway":
            rwy.append(g["coordinates"])
        elif k == "taxiway":
            twy.append({"pts": g["coordinates"], "ref": f["properties"].get("ref", "")})
        elif k == "apron":
            try:
                ap = ShPoly(g["coordinates"][0]).buffer(0)
                if not ap.is_empty:
                    aprons.append(ap)
            except Exception:
                pass
        elif k in ("building", "terminal", "hangar", "construction"):
            try:
                bp = ShPoly(g["coordinates"][0]).buffer(0)
                if bp.is_empty:
                    continue
                if bp.geom_type == "MultiPolygon":
                    bp = max(bp.geoms, key=lambda p: p.area)
                h = max(6.0, min(140.0, f["properties"].get("h") or 10))
                ring = bp.simplify(1.0).exterior
                if ring and len(ring.coords) >= 4:
                    buildings.append({"pts": [[round(x, 2), round(y, 2)] for x, y in ring.coords],
                                      "h": round(h, 1),
                                      "k": k})
            except Exception:
                pass
    if aprons:
        merged = unary_union(aprons).simplify(1.5)
        polys = merged.geoms if merged.geom_type == "MultiPolygon" else [merged]
        apron_pts = [[[round(x, 2), round(y, 2)] for x, y in p.exterior.coords]
                     for p in polys if p.exterior and len(p.exterior.coords) >= 4]
    else:
        apron_pts = []
    return {"aprons": apron_pts, "buildings": buildings, "rwy": rwy, "twy": twy}


def parse_dep_delta(status, sched_time):
    import re as _re
    m = _re.search(r"Dep (\d{2}):(\d{2})", status or "")
    if not m:
        return None
    act = int(m.group(1)) * 60 + int(m.group(2))
    hh, mm = sched_time.split(":")
    s0 = int(hh) * 60 + int(mm)
    d0 = act - s0
    if d0 < -720:
        d0 += 1440
    if d0 > 720:
        d0 -= 1440
    return d0


week = [[0] * 24 for _ in range(7)]
dby_hour = defaultdict(list)
dby_air = defaultdict(list)
for r in csv.DictReader(open(HIST)):
    if r["direction"] != "D" or r["cargo"] != "N" or not r["gate"]:
        continue
    try:
        wd = date.fromisoformat(r["date"]).weekday()
        hh = int(r["sched_time"][:2])
    except ValueError:
        continue
    week[wd][hh] += 1
    d0 = parse_dep_delta(r["status"], r["sched_time"])
    if d0 is not None and -15 <= d0 <= 300:
        dby_hour[hh].append(d0)
        dby_air[r["airline"]].append(d0)
from statistics import median as _med
DELAY_HOUR = [[h, round(_med(v), 1)] for h, v in sorted(dby_hour.items()) if len(v) >= 5]
DELAY_AIR = {a: [round(_med(v), 1), len(v)] for a, v in dby_air.items() if len(v) >= 10}

data = {
    "meta": {
        "from": min(dates), "to": max(dates),
        "records": combos["D-pax"]["gt"].total() if hasattr(combos["D-pax"]["gt"], "total") else sum(combos["D-pax"]["gt"].values()),
        "airlines": airnames,
    },
    "gates": {g: {"lat": la, "lon": lo, "area": area_of(g)} for g, (la, lo) in coords.items()},
    "labels": labels,
    "geo": geo,
    "airports": AIRPORTS,
    "types": TYPES,
    "regs": REGS,
    "taxi": TAXI_STATS,
    "taxigraph": TAXI_GRAPH,
    "csRoutes": CSROUTES,
    "week": week,
    "delayByHour": DELAY_HOUR,
    "delayByAir": DELAY_AIR,
    "geo3d": build_geo3d(),
    "nav": json.load(open(os.path.join(DATA, 'navaids_hkg.json'))),
    "charts": {"pdf": "/charts/VHHH_2009_approach.pdf",
               "fixes": ["BEKOL","DOTMI","PORPA","ROVER","PRAWN","RUMSY","ATTOL","SANDI","TUNNA","LOGAN",
                         "RASSE","SOKOE","LIMES","SIKOU","BREAM","SIERA","MELON","IDOSI","PERCH","ELATO",
                         "ATENA","ASTRA","TROUT","LKC","SMT","CH"]},
    "origins": json.load(open(os.path.join(DATA, 'origins.json'))),
    "live": live_snapshot(),
    "combos": {"D-pax": prune(combos["D-pax"])},
}

payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

css = open(os.path.join(VENDOR, 'leaflet.css')).read()
js = open(os.path.join(VENDOR, 'leaflet.js')).read()
three = open(os.path.join(VENDOR, 'three.min.js')).read()
orbit = open(os.path.join(VENDOR, 'OrbitControls.js')).read()
assert "</script" not in css + js + three + orbit

html = open(os.path.join(BASE, 'map_template.html')).read()
for ph, val in [("__LEAFLET_CSS__", css), ("__LEAFLET_JS__", js), ("__THREE_JS__", three),
                ("__ORBIT_JS__", orbit), ("__DATA__", payload)]:
    assert html.count(ph) == 1, ph
    html = html.replace(ph, val)
open(OUT, "w").write(html)
print(f"wrote {OUT}: {len(html)/1e6:.2f} MB, {nrec} records, {min(dates)}..{max(dates)}")
print(f"geo features: {len(geo['features'])}, labels: {sorted(labels)}")
missing = sorted({g for c in combos.values() for g in c["gt"]} - set(coords))
print("gates in history without coordinates:", missing or "none")
