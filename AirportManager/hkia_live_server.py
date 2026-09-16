import os
BASE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(BASE, 'vendor')
DATA = os.path.join(BASE, 'data')
KEYS = os.path.join(BASE, 'keys')
#!/usr/bin/env python3
import argparse
import csv
import json
import math
import re
import subprocess
import threading
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTML = os.path.join(BASE, "vhhh_gate_map.html")
HIST = os.path.join(DATA, 'hkia_gate_history.csv')
TYPES_PATH = os.path.join(DATA, 'flight_types.json')
REGLOG_PATH = os.path.join(DATA, 'reg_log.json')
RWY_STATS_PATH = os.path.join(DATA, 'runway_stats.json')
TRAILS = {}
TRAIL_META = {}
TRAIL_TS = {}
CESIUM_DIR = os.path.join(VENDOR, 'cesium')
FONTS_DIR = os.path.join(VENDOR, 'fonts')
POLL_ROWS = []
POLL_TS = 0
CHARTS_DIR = os.path.join(VENDOR, 'charts')
GEO_KEY_PATH = os.path.join(KEYS, 'geo_key.txt')
TILECACHE_DIR = os.path.join(DATA, 'tilecache')
TILE_PROVIDERS = ["https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
                  "https://tile.openstreetmap.org/{z}/{x}/{y}.png"]
TILE_SAT = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
ADBX_KEY_PATH = os.path.join(KEYS, 'adbx_key.txt')
OPENAIP_KEY_PATH = os.path.join(KEYS, 'openaip_key.txt')
ADBX_CACHE = {}
WX = {"ts": 0, "data": None}
WIKI_CACHE = {}
APPHOTOS = {"ts": 0, "data": None}
PS_CACHE_PATH = os.path.join(DATA, 'photo_cache.json')
PS_UA = "VHHH-GateMap/1.0 (personal flight-tracking dashboard; contact: local operator)"


def photo_for(reg):
    reg = (reg or "").strip().upper()
    if not reg:
        return {}
    try:
        cache = json.load(open(PS_CACHE_PATH))
    except Exception:
        cache = {}
    e = cache.get(reg)
    if e and time.time() - e.get("ts", 0) < 30 * 86400:
        return e
    try:
        out = subprocess.run(["curl", "-s", "--max-time", "15", "-A", PS_UA,
            f"https://api.planespotters.net/pub/photos/reg/{reg}"],
            capture_output=True, text=True, timeout=25).stdout
        d = json.loads(out)
        ph = (d.get("photos") or [{}])[0]
    except Exception:
        ph = {}
    res = {"thumb": (ph.get("thumbnail_large") or ph.get("thumbnail") or {}).get("src"),
           "link": ph.get("link"), "photographer": ph.get("photographer"),
           "ts": time.time()}
    cache[reg] = res
    try:
        json.dump(cache, open(PS_CACHE_PATH, "w"))
    except Exception:
        pass
    return res
ARRGATES_PATH = os.path.join(DATA, 'arrival_gates.json')
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
FIELDS = ["date", "direction", "cargo", "sched_time", "airline", "flight_no",
          "destination", "terminal", "aisle", "gate", "status"]
LOCK = threading.Lock()
KNOWN = None


def fetch_upstream():
    day = date.today().isoformat()
    url = f"https://www.hongkongairport.com/flightinfo-rest/rest/flights?span=2&date={day}&lang=en"
    out = subprocess.run(["curl", "-s", "--max-time", "45", "-A", UA, url],
                         capture_output=True, text=True, timeout=60).stdout
    return json.loads(out)


def extract(groups):
    rows = []
    for g in groups if isinstance(groups, list) else []:
        if g.get("cargo"):
            continue
        d = "A" if g.get("arrival") else "D"
        for rec in g.get("list", []):
            for f in rec.get("flight", []):
                rows.append({
                    "date": g.get("date", ""),
                    "dir": d,
                    "f": f.get("no", "").replace(" ", ""),
                    "airline": f.get("airline", ""),
                    "gate": rec.get("gate", ""),
                    "time": rec.get("time", ""),
                    "status": rec.get("status", ""),
                    "dest": "|".join(rec.get("destination") or rec.get("origin") or []),
                    "terminal": rec.get("terminal", ""),
                    "aisle": rec.get("aisle", ""),
                })
    return rows


def load_known():
    known = set()
    try:
        for r in csv.DictReader(open(HIST)):
            known.add((r["date"], r["flight_no"], r["direction"], r["sched_time"]))
    except FileNotFoundError:
        pass
    return known


def log_rows(rows):
    global KNOWN
    with LOCK:
        if KNOWN is None:
            KNOWN = load_known()
        new = 0
        with open(HIST, "a", newline="") as f:
            w = csv.writer(f)
            if f.tell() == 0:
                w.writerow(FIELDS)
            for r in rows:
                if r["dir"] != "D":
                    continue
                key = (r["date"], r["f"], "D", r["time"])
                if key in KNOWN or not r["f"] or not r["gate"]:
                    continue
                KNOWN.add(key)
                w.writerow([r["date"], "D", "N", r["time"], r["airline"], r["f"],
                            r["dest"], r["terminal"], r["aisle"], r["gate"], r["status"]])
                new += 1
        return new


def fetch_types():
    ac = []
    for url in ("https://api.adsb.lol/v2/point/22.309/113.915/250",
                "https://opendata.adsb.fi/api/v2/lat/22.309/lon/113.915/dist/250"):
        try:
            out = subprocess.run(["curl", "-s", "--max-time", "30", url],
                                 capture_output=True, text=True, timeout=60).stdout
            ac += json.loads(out).get("ac") or json.loads(out).get("aircraft") or []
            if ac:
                break
        except Exception:
            continue
    snap = {}
    for a in ac:
        fl = (a.get("flight") or "").strip()
        if fl and a.get("t"):
            snap[fl] = a
    return snap


def harvest_types(snap):
    global KNOWN
    with LOCK:
        if KNOWN is None:
            KNOWN = load_known()
        byflight = {}
        for (d, fno, direction, tm) in KNOWN:
            byflight.setdefault(fno, tm and tm or "")
        try:
            store = json.load(open(TYPES_PATH))
        except Exception:
            store = {}
        fa = defaultdict(Counter)
        for r in csv.DictReader(open(HIST)):
            f = r["flight_no"].replace(" ", "")
            if f:
                fa[f][r["airline"]] += 1
        matched = 0
        for f, cnt in fa.items():
            icao = cnt.most_common(1)[0][0]
            a = snap.get(icao + re.sub(r"\D", "", f))
            if not a:
                continue
            e = store.setdefault(f, {"t": {}, "r": {}})
            t, reg = a["t"], a.get("r", "")
            e["t"][t] = e["t"].get(t, 0) + 1
            if reg:
                e["r"][reg] = e["r"].get(reg, 0) + 1
            matched += 1
        json.dump(store, open(TYPES_PATH, "w"))
        return matched


def load_reglog():
    try:
        return json.load(open(REGLOG_PATH))
    except Exception:
        return {}


def harvest_reglog(snap):
    log = load_reglog()
    now = time.time()
    for cs, a in snap.items():
        reg = a.get("r", "")
        if reg:
            log[cs] = [reg, now]
    cut = now - 48 * 3600
    log = {cs: v for cs, v in log.items() if v[1] > cut}
    json.dump(log, open(REGLOG_PATH, "w"))
    return len(log)


def compute_pairs(rows, reglog):
    dep = [r for r in rows if r["dir"] == "D" and r["gate"]]
    arr = [r for r in rows if r["dir"] == "A"]
    depreg = {}
    for r in dep:
        cs = r["airline"] + re.sub(r"\D", "", r["f"])
        e = reglog.get(cs)
        if e:
            depreg[(r["f"], r["time"])] = e[0]
    pairs = {}
    for a in arr:
        cs = a["airline"] + re.sub(r"\D", "", a["f"])
        e = reglog.get(cs)
        if not e:
            continue
        try:
            ah, am = a["time"].split(":")
            arrm = int(ah) * 60 + int(am)
        except ValueError:
            continue
        for r in dep:
            if depreg.get((r["f"], r["time"])) != e[0]:
                continue
            try:
                h, m = r["time"].split(":")
                dm = int(h) * 60 + int(m)
            except ValueError:
                continue
            delta = (dm - arrm) % 1440
            if 0 <= delta <= 300:
                pairs[a["f"]] = {"gate": r["gate"], "next": r["f"]}
                break
    return pairs


RWY_PAIRS = {"L": ("07L", "25R"), "C": ("07C", "25C"), "R": ("07R", "25L")}
_RWY_CLS = None


def runway_centerlines():
    global _RWY_CLS
    if _RWY_CLS is None:
        g = json.load(open(TYPES_PATH.replace("flight_types.json", "taxi_graph.json")))
        T = {t["id"]: (t["lat"], t["lon"]) for t in g["thrs"]}
        _RWY_CLS = {suf: (T[a], T[b]) for suf, (a, b) in RWY_PAIRS.items() if a in T and b in T}
    return _RWY_CLS


def dist_point_seg(p, a, b):
    mx = 111320 * math.cos(math.radians(p[0]))
    mz = 110540
    bx = (b[1] - a[1]) * mx
    bz = (b[0] - a[0]) * mz
    px = (p[1] - a[1]) * mx
    pz = (p[0] - a[0]) * mz
    L2 = bx * bx + bz * bz
    t = max(0.0, min(1.0, (px * bx + pz * bz) / L2)) if L2 else 0.0
    return math.hypot(px - t * bx, pz - t * bz)


RWY_STATE = {}


def classify_runways(ac):
    cls = runway_centerlines()
    counts = {"arr": {}, "dep": {}}
    now = time.time()
    for a in ac:
        hexid = a.get("hex")
        lat, lon, trk = a.get("lat"), a.get("lon"), a.get("track")
        alt, gs = a.get("alt_baro"), a.get("gs")
        if lat is None or lon is None or trk is None:
            continue
        ground = (alt == "ground")
        try:
            altv = 0.0 if ground else float(alt)
            gsv = float(gs or 0)
            rate = float(a.get("baro_rate") or a.get("vert_rate") or 0)
        except (TypeError, ValueError):
            continue
        if not ground and altv > 3000:
            RWY_STATE.pop(hexid, None)
            continue
        if 50 <= trk <= 110:
            dirn = "07"
        elif 215 <= trk <= 285:
            dirn = "25"
        else:
            RWY_STATE.pop(hexid, None)
            continue
        best = None
        for suf, seg in runway_centerlines().items():
            d = dist_point_seg((lat, lon), seg[0], seg[1])
            if best is None or d < best[0]:
                best = (d, suf)
        if not best:
            continue
        d, suf = best
        rwy = dirn + suf
        kind = None
        weight = 1
        if ground and d <= 90 and gsv <= 190:
            kind = "dep"
            prev = RWY_STATE.get(hexid)
            if prev and prev.get("rwy") == rwy and prev.get("gs", 0) < 60 <= gsv:
                weight = 2
        elif not ground and altv < 500 and d <= 90 and gsv <= 190:
            kind = "dep"
            prev = RWY_STATE.get(hexid)
            if prev and prev.get("rwy") == rwy and prev.get("gs", 0) < 80:
                weight = 2
        elif not ground and altv < 2500 and d <= 3000 and gsv <= 250 and rate <= 0:
            kind = "arr"
            if altv < 400 and d <= 150:
                weight = 2
        if kind:
            counts[kind][rwy] = counts[kind].get(rwy, 0) + weight
        if ground or altv < 800:
            RWY_STATE[hexid] = {"gs": gsv, "rwy": rwy, "ts": now}
    for h in [h for h, st in RWY_STATE.items() if now - st.get("ts", 0) > 1800]:
        RWY_STATE.pop(h)
    return counts


def record_runways(counts):
    log = []
    try:
        log = json.load(open(RWY_STATS_PATH))
    except Exception:
        pass
    now = time.time()
    if counts["arr"] or counts["dep"]:
        log.append({"ts": now, "c": counts})
    log = [e for e in log if e["ts"] > now - 6 * 3600]
    json.dump(log, open(RWY_STATS_PATH, "w"))
    return len(log)


def predict_runways():
    try:
        log = json.load(open(RWY_STATS_PATH))
    except Exception:
        return None
    agg = {"arr": {}, "dep": {}}
    n = 0
    for e in log[-72:]:
        n += 1
        for kind in ("arr", "dep"):
            for r, c in e["c"].get(kind, {}).items():
                agg[kind][r] = agg[kind].get(r, 0) + c
    if not n:
        return None
    out = {"n": n}
    for kind in ("arr", "dep"):
        if agg[kind]:
            best = max(agg[kind], key=agg[kind].get)
            tot = sum(agg[kind].values())
            out[kind] = best
            out[kind + "Pct"] = round(100 * agg[kind][best] / tot)
    return out if ("arr" in out or "dep" in out) else None


def adbx_key():
    try:
        return open(ADBX_KEY_PATH).read().strip()
    except Exception:
        return ""


def refresh_arrgates(rows):
    key = adbx_key()
    if not key:
        return 0
    try:
        store = json.load(open(ARRGATES_PATH))
    except Exception:
        store = {}
    day = date.today().isoformat()
    tmr = (date.today() + timedelta(days=1)).isoformat()
    now = time.time()
    store = {f: v for f, v in store.items()
             if now - v.get("ts", 0) < 3 * 86400}
    def within_window(r):
        if r["date"] != day:
            return False
        try:
            h, m = r["time"].split(":")
            t = int(h) * 60 + int(m)
        except ValueError:
            return False
        nw = now_hk() // 60 % 1440
        return -60 <= (t - nw) <= 360
    todo = [r for r in rows if r["dir"] == "A" and within_window(r)
            and not (r["f"] in store and store[r["f"]].get("date") in (day, tmr))]
    done = 0
    for r in todo[:40]:
        try:
            out = subprocess.run(["curl", "-s", "--max-time", "20",
                f"https://aerodatabox.p.rapidapi.com/flights/number/{r['f']}/{r['date']}",
                "-H", f"x-rapidapi-key: {key}",
                "-H", "x-rapidapi-host: aerodatabox.p.rapidapi.com"],
                capture_output=True, text=True, timeout=30).stdout
            legs = json.loads(out)
            gate = term = None
            for leg in legs if isinstance(legs, list) else []:
                arr = leg.get("arrival", {})
                if arr.get("airport", {}).get("icao") == "VHHH" and arr.get("gate"):
                    gate = arr["gate"]
                    term = arr.get("terminal")
                    break
            belt = arr.get("baggageBelt")
            actual = (arr.get("revisedTime") or {}).get("local")
            if gate:
                store[r["f"]] = {"date": r["date"], "gate": gate,
                                 "terminal": term, "belt": belt,
                                 "actual": actual, "ts": time.time()}
                done += 1
        except Exception:
            pass
        time.sleep(0.35)
    if store:
        json.dump(store, open(ARRGATES_PATH, "w"))
    return done


def load_arrgates():
    try:
        store = json.load(open(ARRGATES_PATH))
    except Exception:
        return {}
    return {f: {"gate": v["gate"], "belt": v.get("belt", ""),
                "actual": (v.get("actual") or "")[11:16]}
            for f, v in store.items() if v.get("gate")}


def now_hk():
    return time.time() + 8 * 3600


def rwy_forever(interval=45):
    while True:
        try:
            snap = fetch_types()
            ac = list(snap.values())
            record_runways(classify_runways(ac))
            add_trails(snap)
        except Exception as e:
            print(f"[rwy] {e}", flush=True)
        time.sleep(interval)


def arrgate_forever(interval=7200):
    while True:
        try:
            n = refresh_arrgates(extract(fetch_upstream()))
            if n:
                print(f"[arrgates] +{n} gates from AeroDataBox", flush=True)
        except Exception as e:
            print(f"[arrgates] {e}", flush=True)
        time.sleep(interval)


def add_trails(ac):
    now = time.time()
    for cs, a in ac.items():
        lat, lon = a.get("lat"), a.get("lon")
        if lat is None or lon is None:
            continue
        try:
            alt = float(a.get("alt_baro")) if a.get("alt_baro") != "ground" else 0.0
        except (TypeError, ValueError):
            alt = 0.0
        pts = TRAILS.setdefault(cs, [])
        pts.append([round(lat, 3), round(lon, 3), round(alt)])
        if len(pts) > 40:
            del pts[:len(pts) - 40]
        TRAIL_META[cs] = {"t": a.get("t", ""), "reg": a.get("r", "")}
        TRAIL_TS[cs] = now
    for cs in [c for c, t in TRAIL_TS.items() if now - t > 2700]:
        TRAILS.pop(cs, None)
        TRAIL_META.pop(cs, None)
        TRAIL_TS.pop(cs, None)


def emit_trails():
    out = []
    for cs, pts in TRAILS.items():
        if len(pts) < 2:
            continue
        meta = TRAIL_META.get(cs, {})
        dalt = pts[-1][2] - pts[0][2]
        dirn = "dep" if dalt > 300 else ("arr" if dalt < -300 else "enr")
        out.append({"cs": cs, "t": meta.get("t", ""), "dir": dirn, "pts": pts})
    return out


def adbx_detail(fno, day):
    key = adbx_key()
    ck = f"{fno}|{day}"
    if ck in ADBX_CACHE:
        return ADBX_CACHE[ck]
    if not key or not re.match(r"^[A-Z0-9]{2,4}[0-9]{1,4}[A-Z]?$", fno or ""):
        return None
    try:
        out = subprocess.run(["curl", "-s", "--max-time", "20",
            f"https://aerodatabox.p.rapidapi.com/flights/number/{fno}/{day}",
            "-H", f"x-rapidapi-key: {key}",
            "-H", "x-rapidapi-host: aerodatabox.p.rapidapi.com"],
            capture_output=True, text=True, timeout=30).stdout
        legs = json.loads(out)
    except Exception:
        return None
    best = None
    for leg in legs if isinstance(legs, list) else []:
        dep = leg.get("departure", {})
        arr = leg.get("arrival", {})
        d_icao = dep.get("airport", {}).get("icao")
        a_icao = arr.get("airport", {}).get("icao")
        if d_icao == "VHHH" or a_icao == "VHHH":
            best = leg
            break
    if not best:
        ADBX_CACHE[ck] = {"_miss": True}
        return ADBX_CACHE[ck]
    dep = best.get("departure", {})
    arr = best.get("arrival", {})
    ac = best.get("aircraft", {}) or {}
    delay = None
    try:
        st = (dep.get("scheduledTime") or {}).get("utc")
        rv = (dep.get("revisedTime") or {}).get("utc")
        if st and rv:
            from datetime import datetime as DT
            fmt = lambda x: DT.fromisoformat(x.replace("Z", "+00:00"))
            delay = round((fmt(rv) - fmt(st)).total_seconds() / 60)
    except Exception:
        delay = None
    res = {"model": ac.get("model"), "reg": ac.get("reg"),
           "depGate": dep.get("gate"), "depTerminal": dep.get("terminal"),
           "sched": (dep.get("scheduledTime") or {}).get("local"),
           "revised": (dep.get("revisedTime") or {}).get("local"),
           "delay": delay, "depRunway": dep.get("runway"),
           "arrGate": arr.get("gate"), "arrTerminal": arr.get("terminal"),
           "status": best.get("status")}
    ADBX_CACHE[ck] = res
    return res


def wx_now():
    if time.time() - WX["ts"] < 300 and WX["data"]:
        return WX["data"]
    wind = {}
    try:
        out = subprocess.run(["curl", "-s", "--max-time", "15",
            "https://api.open-meteo.com/v1/forecast?latitude=22.3125&longitude=113.9265"
            "&current=wind_speed_10m,wind_direction_10m,temperature_2m,weather_code"
            "&hourly=visibility&forecast_hours=1&timezone=Asia%2FHong_Kong"],
            capture_output=True, text=True, timeout=25).stdout
        om = json.loads(out)
        cur = om.get("current", {})
        vis = (om.get("hourly", {}).get("visibility") or [None])[0]
        wind = {"speed_kt": round(cur.get("wind_speed_10m", 0) / 1.852, 0),
                "dir": cur.get("wind_direction_10m"), "temp": cur.get("temperature_2m"),
                "code": cur.get("weather_code"), "vis_m": vis}
    except Exception:
        pass
    warnings, lightning = [], False
    try:
        out = subprocess.run(["curl", "-s", "--max-time", "15",
            "https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=rhrread&lang=en"],
            capture_output=True, text=True, timeout=25).stdout
        rr = json.loads(out)
        warnings = [w.get("message") for w in rr.get("warningMessage", []) if w.get("message")]
        lightning = any(x.get("occur") == "true" for x in rr.get("lightning", {}).get("data", []))
    except Exception:
        pass
    rec = head = cross = None
    try:
        import math as _m
        ws = float(wind.get("speed_kt") or 0)
        wd = float(wind.get("dir") or 0)
        h07 = ws * _m.cos(_m.radians(wd - 70))
        cross = round(abs(ws * _m.sin(_m.radians(wd - 70))), 1)
        head = round(h07, 1)
        rec = "07" if h07 >= 0 else "25"
    except Exception:
        pass
    data = {"wind": wind, "warnings": warnings, "lightning": lightning,
            "rec": rec, "head": head, "cross": cross}
    WX["ts"] = time.time()
    WX["data"] = data
    return data


def wimage(title):
    title = (title or "").strip().replace(" ", "_")
    if not title or not re.match(r"^[A-Za-z0-9_\-\.]+$", title):
        return {}
    if title in WIKI_CACHE:
        return WIKI_CACHE[title]
    try:
        out = subprocess.run(["curl", "-s", "--max-time", "15",
            "-A", "VHHH-GateMap/1.0 (personal dashboard)",
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"],
            capture_output=True, text=True, timeout=25).stdout
        d = json.loads(out)
    except Exception:
        return {}
    res = {"thumb": (d.get("thumbnail") or {}).get("source"),
           "extract": (d.get("extract") or "")[:160]}
    WIKI_CACHE[title] = res
    return res


def openaip_fixes():
    try:
        tok = open(OPENAIP_KEY_PATH).read().strip()
    except Exception:
        tok = ""
    if not tok:
        return {"error": "no token saved"}
    out = subprocess.run(["curl", "-s", "--max-time", "20",
        f"https://api.openaip.net/api/waypoints?token={tok}&limit=500&bbox=109,18.5,118.5,26"],
        capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        return {"error": "api.openaip.net unreachable (their DNS/API is offline)"}
    try:
        d = json.loads(out.stdout)
    except Exception:
        return {"error": "openaip returned invalid data"}
    fixes = []
    for f in d if isinstance(d, list) else d.get("data", []):
        pts = f.get("coordinates") or {}
        la, lo = pts.get("latitude"), pts.get("longitude")
        if la is None:
            continue
        fixes.append({"id": f.get("name") or f.get("id"), "la": la, "lo": lo})
    return {"count": len(fixes), "fixes": fixes}


def airport_photos():
    if time.time() - APPHOTOS["ts"] < 6 * 3600 and APPHOTOS["data"]:
        return APPHOTOS["data"]
    try:
        out = subprocess.run(["curl", "-s", "--max-time", "20", "-A",
            "VHHH-GateMap/1.0 (personal dashboard)",
            "https://en.wikipedia.org/api/rest_v1/page/media-list/Hong_Kong_International_Airport"],
            capture_output=True, text=True, timeout=30).stdout
        d = json.loads(out)
    except Exception:
        return {"photos": []}
    photos = []
    for it in d.get("items", []):
        srcset = it.get("srcset") or []
        if not srcset:
            continue
        title = (it.get("title") or "").replace("File:", "").replace(" ", "_")
        if title:
            from urllib.parse import quote
            photos.append("https://commons.wikimedia.org/wiki/Special:FilePath/" + quote(title) + "?width=2560")
    photos = photos[:12]
    APPHOTOS["ts"] = time.time()
    APPHOTOS["data"] = {"photos": photos}
    return APPHOTOS["data"]


def common_types():
    try:
        store = json.load(open(TYPES_PATH))
    except Exception:
        return {}
    out = {}
    for f, e in store.items():
        if e.get("t"):
            out[f] = max(e["t"], key=e["t"].get)
    return out


def get_rows():
    global POLL_ROWS, POLL_TS
    if not POLL_ROWS or time.time() - POLL_TS > 300:
        POLL_ROWS = extract(fetch_upstream())
        POLL_TS = time.time()
    return POLL_ROWS


def poll_forever(interval=300):
    while True:
        try:
            rows = extract(fetch_upstream())
            global POLL_ROWS, POLL_TS
            POLL_ROWS = rows
            POLL_TS = time.time()
            snap = fetch_types()
            m = harvest_types(snap)
            t = harvest_reglog(snap)
            arrgate_forever
            if n or m:
                print(f"[poll] +{n} rows, +{m} type matches, reglog {t} -> archive", flush=True)
        except Exception as e:
            print(f"[poll] failed: {e}", flush=True)
        time.sleep(interval)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/live"):
            try:
                rows = extract(fetch_upstream())
                new = log_rows(rows)
                pairs = compute_pairs(rows, load_reglog())
                body = json.dumps({"ts": time.time(), "logged": new, "rows": rows,
                                   "types": common_types(), "pairs": pairs,
                                   "extArr": load_arrgates(),
                                   "trails": emit_trails(),
                                   "wx": wx_now(),
                                   "runway": predict_runways()}).encode()
                self.send_response(200)
            except Exception as e:
                body = json.dumps({"error": str(e), "rows": []}).encode()
                self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/openaip-fixes"):
            body = json.dumps(openaip_fixes()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/apphotos"):
            body = json.dumps(airport_photos()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/wx"):
            body = json.dumps(wx_now()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/wimage"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            body = json.dumps(wimage(q.get("title", [""])[0])).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/photo"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            res = photo_for(q.get("reg", [""])[0])
            body = json.dumps(res).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/adbx"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            fno = (q.get("fno", [""])[0] or "").replace(" ", "").upper()
            day = q.get("date", [date.today().isoformat()])[0]
            res = adbx_detail(fno, day)
            body = json.dumps(res or {"_miss": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/tiles/"):
            import os
            from urllib.parse import urlparse, parse_qs
            parts = self.path.split("/")
            qs = parse_qs(urlparse(self.path).query)
            sat = "1" in qs.get("sat", ["0"])
            if len(parts) < 5:
                self.send_error(404); return
            z, x = parts[2], parts[3]
            y = parts[4].split(".")[0]
            if not (z.isdigit() and x.isdigit() and y.isdigit()):
                self.send_error(404); return
            os.makedirs(os.path.join(TILECACHE_DIR, z, x), exist_ok=True)
            p = os.path.join(TILECACHE_DIR, z, x, y + ".png")
            if not os.path.isfile(p):
                import random
                if sat:
                    url = TILE_SAT.replace("{z}", z).replace("{y}", y).replace("{x}", x)
                else:
                    prov = random.choice(TILE_PROVIDERS)
                    url = prov.replace("{z}", z).replace("{x}", x).replace("{y}", y)
                try:
                    data = subprocess.run(["curl", "-s", "--max-time", "15", "-A",
                        "VHHH-GateMap/1.0 (personal flight dashboard; contact: local operator)", url],
                        capture_output=True, timeout=25).stdout
                except Exception:
                    data = b""
                ok_img = len(data) > 100 and (data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8"))
                if not ok_img:
                    alt = "https://tile.openstreetmap.org/{z}/{x}/{y}.png".replace("{z}", z).replace("{x}", x).replace("{y}", y)
                    data = subprocess.run(["curl", "-s", "--max-time", "15", "-A",
                        "VHHH-GateMap/1.0 (personal flight dashboard; contact: local operator)", alt],
                        capture_output=True, timeout=25).stdout
                    if len(data) < 100 or not data.startswith(b"\x89PNG"):
                        self.send_error(502); return
                with open(p, "wb") as f:
                    f.write(data)
            try:
                body = open(p, "rb").read()
            except OSError:
                self.send_error(404); return
            ctype = "image/jpeg" if body.startswith(b"\xff\xd8") else "image/png"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "public, max-age=604800")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/inbound"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            fno = (q.get("fno", [""])[0] or "").replace(" ", "").upper()
            day = q.get("date", [date.today().isoformat()])[0]
            res = adbx_detail(fno, day) or {}
            reg = res.get("reg")
            out = {"reg": reg, "model": res.get("model")}
            if reg:
                reglog = load_reglog()
                for r in get_rows():
                    if r["dir"] != "A":
                        continue
                    cs = r["airline"] + re.sub(r"\D", "", r["f"])
                    e = reglog.get(cs)
                    if e and e[0] == reg:
                        out.update({"f": r["f"], "from": r["dest"], "time": r["time"],
                                    "status": r["status"], "cs": cs})
                        tr = TRAILS.get(cs)
                        if tr and len(tr) >= 2:
                            la, lo = tr[-1][0], tr[-1][1]
                            out["dist_km"] = round(dist_point_seg((la, lo), (22.3075, 113.9328), (22.2967, 113.8994)) / 100) / 10
                        break
            body = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/day"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            day = q.get("date", [date.today().isoformat()])[0]
            rows = []
            try:
                for r in csv.DictReader(open(HIST)):
                    if r["date"] == day and r["direction"] == "D" and r["gate"]:
                        rows.append({"date": day, "dir": "D", "f": r["flight_no"].replace(" ", ""),
                                     "airline": r["airline"], "gate": r["gate"], "time": r["sched_time"],
                                     "status": r["status"], "dest": r["destination"]})
            except Exception:
                pass
            body = json.dumps({"rows": rows}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/reg"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            reg = (q.get("reg", [""])[0] or "").upper()
            flights = {}
            try:
                store = json.load(open(TYPES_PATH))
                for f, e in store.items():
                    for r2, n in (e.get("r") or {}).items():
                        if r2.upper() == reg:
                            flights[f] = n
            except Exception:
                pass
            moves = []
            seen = set()
            for r in csv.DictReader(open(HIST)):
                f = r["flight_no"].replace(" ", "")
                if f in flights and f not in seen:
                    seen.add(f)
                if r["date"] in seen:
                    continue
            moves = [{"date": r["date"], "f": r["flight_no"].replace(" ", ""),
                      "gate": r["gate"], "dest": r["destination"], "time": r["sched_time"],
                      "status": r["status"]}
                     for r in csv.DictReader(open(HIST))
                     if r["flight_no"].replace(" ", "") in flights and r["gate"]][-300:]
            body = json.dumps({"reg": reg, "flights": sorted(flights), "moves": moves}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/fonts/"):
            import os
            rel = self.path[len("/fonts/"):].split("?")[0]
            p = os.path.normpath(os.path.join(FONTS_DIR, rel))
            if not p.startswith(FONTS_DIR) or not os.path.isfile(p):
                self.send_error(404); return
            body = open(p, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "font/woff2")
            self.send_header("Cache-Control", "public, max-age=2592000")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/config"):
            try:
                k = open(GEO_KEY_PATH).read().strip()
            except Exception:
                k = ""
            body = json.dumps({"geoKey": k}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/charts/"):
            import os
            rel = self.path[len("/charts/"):].split("?")[0]
            p = os.path.normpath(os.path.join(CHARTS_DIR, rel))
            if not p.startswith(CHARTS_DIR) or not os.path.isfile(p):
                self.send_error(404); return
            body = open(p, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/cesium/"):
            import os
            rel = self.path[len("/cesium/"):].split("?")[0]
            p = os.path.normpath(os.path.join(CESIUM_DIR, rel))
            if not p.startswith(CESIUM_DIR) or not os.path.isfile(p):
                self.send_error(404)
                return
            ext = p.rsplit(".", 1)[-1].lower()
            ctype = {".js": "application/javascript", ".css": "text/css",
                     ".json": "application/json", ".png": "image/png",
                     ".jpg": "image/jpeg", ".svg": "image/svg+xml",
                     ".wasm": "application/wasm", ".ktx2": "image/ktx2",
                     ".bin": "application/octet-stream", ".html": "text/html",
                     ".woff": "font/woff", ".woff2": "font/woff2"}.get(ext, "application/octet-stream")
            try:
                body = open(p, "rb").read()
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(body)
        elif self.path in ("/", "/index.html"):
            try:
                body = open(HTML, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_error(404, "run build_gate_map.py first")
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8461)
    a = ap.parse_args()
    threading.Thread(target=poll_forever, daemon=True).start()
    threading.Thread(target=arrgate_forever, daemon=True).start()
    threading.Thread(target=rwy_forever, daemon=True).start()
    print(f"VHHH live map : http://localhost:{a.port}  (archive logging every 5 min)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
