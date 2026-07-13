"""Geocode permit addresses: Census batch API, Nominatim fallback, JSON cache."""
import csv
import io
import json
import re
import time

import requests

ADDR_RE = re.compile(
    r"^(?P<street>.+),\s*(?P<city>[^,]+),\s*MD\s*(?P<zip>\d{5})(-\d{4})?$")


def split_address(address):
    m = ADDR_RE.match(address)
    if not m:
        return None
    return m.group("street"), m.group("city"), m.group("zip")


CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "howard-county-permit-map/1.0"}
BATCH_SIZE = 5000


def _census_batch(addresses):
    """One batch call. Returns {address: entry} for matches only."""
    rows = io.StringIO()
    writer = csv.writer(rows)
    indexed = []
    for addr in addresses:
        parts = split_address(addr)
        if parts:
            writer.writerow([len(indexed), *parts[:2], "MD", parts[2]])
            indexed.append(addr)
    if not indexed:
        return {}
    resp = requests.post(
        CENSUS_URL,
        data={"benchmark": "Public_AR_Current", "vintage": "Current_Current"},
        files={"addressFile": ("addresses.csv", rows.getvalue())},
        timeout=300)
    resp.raise_for_status()
    out = {}
    for row in csv.reader(io.StringIO(resp.text)):
        if len(row) < 12 or row[2] != "Match":
            continue
        lng, lat = (float(v) for v in row[5].split(","))
        out[indexed[int(row[0])]] = {
            "lat": lat, "lng": lng,
            "quality": "exact" if row[3] == "Exact" else "approx",
            "tract": row[10],
        }
    return out


def _nominatim(address):
    resp = requests.get(
        NOMINATIM_URL,
        params={"q": address, "format": "json", "limit": 1},
        headers=HEADERS, timeout=30)
    resp.raise_for_status()
    hits = resp.json()
    if not hits:
        return None
    return {"lat": float(hits[0]["lat"]), "lng": float(hits[0]["lon"]),
            "quality": "approx", "tract": None}


def geocode_all(addresses, cache_path):
    """Geocode every address, using and updating the JSON cache."""
    cache = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
    todo = sorted({a for a in addresses if a not in cache})

    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i:i + BATCH_SIZE]
        matched = _census_batch(batch)
        for addr in batch:
            if addr in matched:
                cache[addr] = matched[addr]
        for addr in batch:
            if addr in cache:
                continue
            time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
            hit = _nominatim(addr)
            cache[addr] = hit if hit else {"quality": "failed"}

    if todo:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True))
    return cache
