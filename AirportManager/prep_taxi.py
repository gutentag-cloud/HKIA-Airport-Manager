import os
BASE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(BASE, 'vendor')
DATA = os.path.join(BASE, 'data')
KEYS = os.path.join(BASE, 'keys')
#!/usr/bin/env python3
import csv
import json
import math
import re
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

ASSETS = DATA
HIST = os.path.join(DATA, 'hkia_gate_history.csv')

geo = json.load(open(os.path.join(VENDOR, 'vhhh_geometry.json')))


def hav(a, b):
    R = 6371000
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


nodes = []
nidx = {}
adj = []


def node(lat, lon):
    k = (round(lat, 5), round(lon, 5))
    if k not in nidx:
        nidx[k] = len(nodes)
        nodes.append([k[0], k[1]])
        adj.append([])
    return nidx[k]


def link(a, b):
    if a == b:
        return
    d = hav(nodes[a], nodes[b])
    adj[a].append([b, d])
    adj[b].append([a, d])


for e in geo["elements"]:
    t = e.get("tags", {})
    if t.get("aeroway") != "taxiway":
        continue
    pts = [[p["lat"], p["lon"]] for p in e.get("geometry", [])]
    prev = None
    for p in pts:
        i = node(p[0], p[1])
        if prev is not None:
            link(prev, i)
        prev = i

gate_node = {}
coords = {r["gate"]: (float(r["lat"]), float(r["lon"])) for r in csv.DictReader(open(os.path.join(DATA, 'vhhh_gates.csv')))}
for g, (la, lo) in coords.items():
    best, bd = None, 1e9
    for i, (nla, nlo) in enumerate(nodes):
        d = hav((la, lo), (nla, nlo))
        if d < bd:
            best, bd = i, d
    if best is not None and bd <= 500:
        gate_node[g] = best

runways = defaultdict(list)
for e in geo["elements"]:
    t = e.get("tags", {})
    if t.get("aeroway") == "runway" and t.get("ref"):
        runways[t["ref"]].append([[p["lat"], p["lon"]] for p in e.get("geometry", [])])

thrs = []
for ref, ways in runways.items():
    ends = []
    for pts in ways:
        ends.append(tuple(pts[0]))
        ends.append(tuple(pts[-1]))
    a = min(ends)
    b = max(ends)
    ids = ref.split("/")
    for id_, p in ((ids[0], a), (ids[1], b)):
        best, bd = None, 1e9
        for i, np_ in enumerate(nodes):
            d = hav(p, np_)
            if d < bd:
                best, bd = i, d
        if best is not None:
            thrs.append({"id": id_, "node": best, "lat": p[0], "lon": p[1]})

graph = {"nodes": nodes, "adj": adj, "gateNode": gate_node, "thrs": thrs}
json.dump(graph, open(os.path.join(DATA, 'taxi_graph.json'), "w"))
print(f"graph: {len(nodes)} nodes, {sum(len(a) for a in adj)//2} edges, {len(gate_node)}/{len(coords)} gates linked, thresholds: {[t['id'] for t in thrs]}")


def parse_actual(status):
    m = re.search(r"Dep (\d{2}):(\d{2})", status or "")
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def sched_min(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


by_gate = defaultdict(list)
by_hour = defaultdict(list)
for r in csv.DictReader(open(HIST)):
    if r["direction"] != "D" or r["cargo"] != "N" or not r["gate"] or not r["gate"] in coords:
        continue
    act = parse_actual(r["status"])
    if act is None:
        continue
    s = sched_min(r["sched_time"])
    d = act - s
    if d < -720:
        d += 1440
    if d > 720:
        d -= 1440
    if 3 <= d <= 60:
        by_gate[r["gate"]].append(d)
        try:
            by_hour[int(r["sched_time"][:2])].append(d)
        except ValueError:
            pass

stats = {
    "byGate": {g: [round(median(v), 1), len(v)] for g, v in by_gate.items() if len(v) >= 5},
    "byHour": [[h, round(median(v), 1), len(v)] for h, v in sorted(by_hour.items()) if len(v) >= 5],
}
json.dump(stats, open(os.path.join(DATA, 'taxi_stats.json'), "w"))
ng = len(stats["byGate"])
tot = sum(len(v) for v in by_gate.values())
print(f"taxi stats: {ng} gates with medians (from {tot} observations), hours: {len(stats['byHour'])}")
sample = sorted(stats["byGate"].items(), key=lambda kv: -kv[1][1])[:5]
print("sample:", [(g, m) for g, (m, n) in sample])
print("hourly:", [(h, m) for h, m, n in stats["byHour"]][:8], "...")
