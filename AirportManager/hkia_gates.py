import os
BASE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(BASE, 'vendor')
DATA = os.path.join(BASE, 'data')
KEYS = os.path.join(BASE, 'keys')
#!/usr/bin/env python3
"""HKIA (VHHH) gate history tool.

Uses the public endpoints behind hongkongairport.com flight boards:
  live:  /flightinfo-rest/rest/flights?span=1&date=YYYY-MM-DD&lang=en
  past:  /flightinfo-rest/rest/flights/past?span=1&date=YYYY-MM-DD&lang=en
The 'past' endpoint serves a rolling 91-day archive; 'live' serves today forward.

Usage:
  python3 hkia_gates.py backfill [--days 91] [--force]     fetch all available history into CSV
  python3 hkia_gates.py update                             fetch today (and yesterday) into CSV
  python3 hkia_gates.py report --flight CX880              gate history for one flight number
  python3 hkia_gates.py report --airline CPA               gate history for one airline (ICAO code)
  python3 hkia_gates.py report --top 30                    most frequent flights by gate consistency
"""
import argparse
import csv
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date, timedelta

BASE = "https://www.hongkongairport.com/flightinfo-rest/rest"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
CSV_PATH = os.path.join(DATA, 'hkia_gate_history.csv')
FIELDS = ["date", "direction", "cargo", "sched_time", "airline", "flight_no",
          "destination", "terminal", "aisle", "gate", "status"]


def fetch(day: date, past: bool, retries: int = 4):
    kind = "flights/past" if past else "flights"
    url = f"{BASE}/{kind}?span=1&date={day.isoformat()}&lang=en"
    for attempt in range(retries):
        try:
            out = subprocess.run(
                ["curl", "-s", "--max-time", "90", "-A", UA,
                 "-H", "Accept: */*", "-H", "Accept-Language: en-US,en;q=0.9",
                 "-H", f"Referer: https://www.hongkongairport.com/en/flights/departures/passenger.page",
                 url],
                capture_output=True, text=True, timeout=120).stdout
            data = json.loads(out)
            if isinstance(data, list):
                return data
            raise ValueError(data.get("message", str(data)[:100]))
        except Exception as e:
            if attempt == retries - 1:
                print(f"  ! {day}: {e}", file=sys.stderr)
                return None
            time.sleep(20 + 20 * attempt)


def rows_for(day: date, past: bool):
    data = fetch(day, past)
    if not isinstance(data, list):
        return []
    out = []
    for group in data:
        d = group.get("date") or day.isoformat()
        direction = "A" if group.get("arrival") else "D"
        cargo = "Y" if group.get("cargo") else "N"
        for rec in group.get("list", []):
            for f in rec.get("flight", []):
                out.append({
                    "date": d,
                    "direction": direction,
                    "cargo": cargo,
                    "sched_time": rec.get("time", ""),
                    "airline": f.get("airline", ""),
                    "flight_no": f.get("no", "").replace(" ", ""),
                    "destination": "|".join(rec.get("destination") or rec.get("origin") or []),
                    "terminal": rec.get("terminal", ""),
                    "aisle": rec.get("aisle", ""),
                    "gate": rec.get("gate", ""),
                    "status": rec.get("status", ""),
                })
    return out


def load_existing():
    seen = set()
    try:
        with open(CSV_PATH, newline="") as f:
            for row in csv.DictReader(f):
                seen.add((row["date"], row["flight_no"], row["direction"], row["sched_time"]))
    except FileNotFoundError:
        pass
    return seen


def append_rows(rows):
    new = 0
    seen = load_existing()
    with open(CSV_PATH, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if f.tell() == 0:
            w.writeheader()
        for r in rows:
            key = (r["date"], r["flight_no"], r["direction"], r["sched_time"])
            if key in seen or not r["flight_no"]:
                continue
            seen.add(key)
            w.writerow(r)
            new += 1
    return new


def cmd_backfill(days, force):
    done = set()
    if not force:
        try:
            with open(CSV_PATH, newline="") as f:
                done = {r["date"] for r in csv.DictReader(f)}
        except FileNotFoundError:
            pass
    total = 0
    for offset in range(days, 0, -1):
        day = date.today() - timedelta(days=offset)
        if not force and day.isoformat() in done:
            continue
        rows = rows_for(day, past=True)
        n = append_rows(rows)
        total += n
        print(f"{day} -> {len(rows)} records (+{n} new)")
        time.sleep(8.0)
    print(f"done, {total} new rows -> {CSV_PATH}")


def cmd_update():
    total = 0
    for offset in (1, 0):
        day = date.today() - timedelta(days=offset)
        rows = rows_for(day, past=(offset == 1))
        total += append_rows(rows)
    print(f"update complete, {total} new rows -> {CSV_PATH}")


def cmd_report(flight, airline, top):
    with open(CSV_PATH, newline="") as f:
        rows = list(csv.DictReader(f))
    if flight:
        rows = [r for r in rows if r["flight_no"].upper() == flight.upper().replace(" ", "")]
    if airline:
        a = airline.upper()
        rows = [r for r in rows if r["airline"].upper() == a]

    by_flight = defaultdict(list)
    for r in rows:
        if r["gate"]:
            by_flight[r["flight_no"]].append(r["gate"])

    if flight or airline:
        print(f"{'flight':<10}{'n':>4}  gate distribution")
        for fn in sorted(by_flight):
            c = Counter(by_flight[fn])
            dist = ", ".join(f"{g}:{v} ({v * 100 // sum(c.values())}%)" for g, v in c.most_common())
            print(f"{fn:<10}{len(c.total() if hasattr(c,'total') else sum(c.values())):>4}  {dist}")
        return

    scored = []
    for fn, gates in by_flight.items():
        if len(gates) < 5:
            continue
        g, n = Counter(gates).most_common(1)[0]
        scored.append((n / len(gates), len(gates), fn, g))
    scored.sort(reverse=True)
    print(f"{'flight':<10}{'n':>4}{'consistency':>13}  usual gate")
    for consistency, n, fn, g in scored[:top]:
        print(f"{fn:<10}{n:>4}{consistency:>12.0%}  {g}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--days", type=int, default=91)
    b.add_argument("--force", action="store_true")
    sub.add_parser("update")
    r = sub.add_parser("report")
    r.add_argument("--flight")
    r.add_argument("--airline")
    r.add_argument("--top", type=int, default=30)
    a = p.parse_args()
    if a.cmd == "backfill":
        cmd_backfill(a.days, a.force)
    elif a.cmd == "update":
        cmd_update()
    else:
        cmd_report(a.flight, a.airline, a.top)
