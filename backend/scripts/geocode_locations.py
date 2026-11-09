#!/usr/bin/env python3
"""One-time operator geocoding, not a live/autocomplete service.

Nominatim policy: https://operations.osmfoundation.org/policies/nominatim/
Single process/thread, >=1.1s between requests, persistent cache, descriptive UA.
Only public civic addresses are submitted, never tenants, names or lease data.
OSM data © OpenStreetMap contributors, ODbL. Cache/review files are local data.
Requires an explicit env-file and DB name; dry-run still caches public responses.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


COMMUNITIES = [
    ("parkview pointe", "West St. Paul"),
    ("forest grove", "Headingley"),
    ("garson", "Garson"),
    ("grande pointe", "Grande Pointe"),
    ("wheatland", "Dugald"),
    ("dugald", "Dugald"),
    ("oakbank", "Oakbank"),
    ("prairie view lakes", "La Salle"),
    ("oak river meadow", "Île-des-Chênes"),
    ("mountain ridge", "Stony Mountain"),
    ("sunset acres", "New Bothwell"),
    ("templeton", "Winnipeg"),
    ("finnigan", "Ste. Anne"),
]
SUFFIX = {"ave": "avenue", "st": "street", "dr": "drive", "blvd": "boulevard", "cres": "crescent", "rd": "road", "ln": "lane", "pl": "place", "ct": "court"}


def normalize(value):
    value = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    value = re.sub(r"sand\s+piper", "sandpiper", value, flags=re.I)
    words = re.sub(r"[^a-z0-9]+", " ", value.lower()).split()
    words = [SUFFIX.get(w, w) for w in words]
    # Winnipeg bilingual names such as "Avenue Guay Avenue".
    if len(words) > 2 and words[0] == words[-1] and words[0] in SUFFIX.values():
        words = words[1:]
    return " ".join(words)


def query_address(row):
    address = row["address"].split(",")[0].strip()
    community = (row.get("community") or "").lower()
    municipality = row.get("municipality") or row.get("city") or ""
    city = re.sub(r"^(?:rural municipality of |r\.?\s*m\.?\s*of )+", "", municipality, flags=re.I)
    city = re.sub(r",?\s*(?:Manitoba|MB)$", "", city, flags=re.I).strip()
    city = re.sub(r"^City of ", "", city, flags=re.I)
    for needle, value in COMMUNITIES:
        if needle in community:
            city = value
            break
    if "clubhouse" in address.lower():
        city = "Lorette"
    if "sand piper" in address.lower() or "sandpiper" in address.lower():
        city = "Landmark"
        address = re.sub(r"Sand\s*Piper.*$", "Sand Piper Trail", address, flags=re.I)
    if "froese" in address.lower():
        city = "Headingley"
    if address == "79-100 GPM condo":
        address = "100 Grande Pointe Meadows Boulevard"
        city = "Grande Pointe"
    # A condo unit is not the civic house number. Never claim a unit-level pin.
    unit = bool(re.match(r"\d+\s*-\s*\d+", address)) or "GPM condo" in row["address"] or "Sand Piper" in row["address"]
    address = re.sub(r"^\d+\s*-\s*(?=\d)", "", address)
    return address, city, unit


def classify(result, street, city, unit=False):
    """Return precision only when country/state/community AND street match.

    Nominatim often returns a road when asked for a missing house. House number
    and road must both agree, not just addresstype or a nonempty response.
    """
    a = result.get("address", {})
    try:
        lat, lng = float(result["lat"]), float(result["lon"])
    except (KeyError, ValueError, TypeError):
        return "not_found", "invalid coordinates"
    if a.get("country_code") != "ca" or a.get("state") != "Manitoba" or not (49 <= lat <= 60 and -102 <= lng <= -89):
        return "not_found", "outside Manitoba"
    locations = " ".join(str(a.get(k, "")) for k in ["city", "town", "village", "hamlet", "municipality", "county", "city_district", "suburb"])
    # Rural municipality names vary; do not accept only province or county
    # when the intended settlement is a different town.
    community_fields = [a.get(k, "") for k in ["city", "town", "village", "hamlet", "municipality", "county", "city_district", "suburb"]]
    if not any(normalize(city) == normalize(re.sub(r"^(?:rural municipality of|city of)\s+", "", str(value), flags=re.I)) for value in community_fields):
        return "not_found", "wrong community: " + locations
    number = re.match(r"^(\d+[A-Za-z]?)\s+(.+)$", street)
    expected_road = number.group(2) if number else street
    roads = [a.get(k, "") for k in ["road", "pedestrian", "residential", "square"]]
    if normalize(expected_road) not in [normalize(r) for r in roads if r]:
        return ("not_found", "street mismatch / missing East-West direction; manual review") if any(roads) else ("locality", "locality centroid; not plotted")
    if number and normalize(str(a.get("house_number", ""))) == normalize(number.group(1)) and not unit:
        return "house", "house number and street match"
    return "street", "street only; manual parcel pin needed" if not unit else "shared or normalized civic street; manual pin needed"


class Geocoder:
    def __init__(self, path, endpoint, user_agent):
        self.path, self.endpoint, self.user_agent = path, endpoint, user_agent
        self.cache = json.loads(path.read_text()) if path.exists() else {}
        self.last_request = 0.0

    def search(self, street, city):
        params = dict(street=street, city=city, state="Manitoba", country="Canada", countrycodes="ca", format="jsonv2", addressdetails=1, limit=5, viewbox="-102,60,-89,49", bounded=1)
        key = self.endpoint + "?" + urlencode(params)
        if key in self.cache:
            return self.cache[key]
        time.sleep(max(0, 1.1 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        # Fail closed on HTTP errors/rate limiting; never cache errors as misses.
        for attempt in range(4):
            try:
                with urlopen(Request(key, headers={"User-Agent": self.user_agent, "Accept": "application/json"}), timeout=35) as response:
                    results = json.load(response)
                break
            except (HTTPError, URLError, TimeoutError) as exc:
                if attempt == 3 or (isinstance(exc, HTTPError) and exc.code not in {429, 502, 503, 504}):
                    raise
                time.sleep([5, 15, 30][attempt])
                self.last_request = time.monotonic()
        self.cache[key] = results
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.cache, indent=2))
        temp.replace(self.path)
        return results

    def locate(self, row):
        street, city, unit = query_address(row)
        best, precision, reason = None, "not_found", "no matching street in expected community"
        queries = [street]
        without_number = re.sub(r"^\d+[A-Za-z]?\s+", "", street)
        if without_number != street:
            queries.append(without_number)
        for query in queries:
            results = self.search(query, city)
            for result in results:
                p, why = classify(result, street, city, unit)
                rank = {"house": 3, "street": 2, "locality": 1, "not_found": 0}
                if rank[p] > rank[precision]:
                    best, precision, reason = result, p, why
                elif best is None and precision == "not_found":
                    reason = why
            if precision == "house":
                houses = [r for r in results if classify(r, street, city, unit)[0] == "house"]
                if any(abs(float(r["lat"]) - float(best["lat"])) > 0.0005 or abs(float(r["lon"]) - float(best["lon"])) > 0.0005 for r in houses):
                    best, precision, reason = None, "not_found", "ambiguous matching house results; manual review"
                    break
            if precision in {"house", "street"}:
                break
        plottable = precision in {"house", "street"}
        return dict(row, query_street=street, expected_city=city, precision=precision,
                    latitude=round(float(best["lat"]), 6) if plottable else None,
                    longitude=round(float(best["lon"]), 6) if plottable else None,
                    display_name=best.get("display_name", "") if best else "", reason=reason,
                    osm_type=best.get("osm_type", "") if best else "", osm_id=best.get("osm_id", "") if best else "")


def flag_clusters(rows):
    clusters = defaultdict(list)
    for row in rows:
        if row["latitude"] is not None:
            clusters[(row["latitude"], row["longitude"])].append(row)
    for group in clusters.values():
        if len({normalize(r["address"]) for r in group}) > 1:
            for row in group:
                # Street was validated before clustering; no locality centroid
                # can enter the cluster. Never label a shared point exact.
                row["precision"] = "street"
                row["reason"] += "; identical shared point, manual pin needed"


async def run(args):
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=True)
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL missing in explicit env-file")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            actual = (await conn.execute(text("select current_database()"))).scalar_one()
            if actual != args.database:
                raise SystemExit("Refusing: actual database does not match --database")
            if actual != "officehub_workspace_qa_20261106":
                raise SystemExit("Preview-only safety guard: no other DB may be changed")
            rental = list((await conn.execute(text("select id::text, street_address as address, municipality, city, group_name as community, latitude, longitude, geocode_precision from rental_properties order by id"))).mappings())
            lots = list((await conn.execute(text("select l.id::text, l.civic_address as address, d.municipality, d.name as community, l.latitude, l.longitude, l.geocode_precision from core.lots l join core.developments d on d.id=l.development_id order by l.id"))).mappings())
        geocoder = Geocoder(Path(args.cache), args.endpoint, args.user_agent)
        rows = []
        for kind, records in [("rental", rental), ("lot", lots)]:
            for r in records:
                if args.only_missing and r["latitude"] is not None and r["longitude"] is not None and r["geocode_precision"] in {"house", "street"}:
                    continue
                source = dict(r, kind=kind)
                result = geocoder.locate(source)
                rows.append(result)
                print(f"{kind} {r['id']} {r['address']} -> {result['precision']} ({result['expected_city']})", flush=True)
        flag_clusters(rows)
        fields = ["kind", "id", "address", "community", "municipality", "query_street", "expected_city", "precision", "latitude", "longitude", "reason", "display_name", "osm_type", "osm_id"]
        output = Path(args.csv)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        if not args.dry_run:
            async with engine.begin() as conn:
                for row in rows:
                    table = "rental_properties" if row["kind"] == "rental" else "core.lots"
                    await conn.execute(text(f"update {table} set latitude=:latitude,longitude=:longitude,geocode_precision=:precision,geocode_source=:source,geocoded_at=:now where id::text=:id"), dict(row, source="osm_nominatim", now=datetime.now(timezone.utc)))
        for kind in ["rental", "lot"]:
            print(kind, dict(Counter(r["precision"] for r in rows if r["kind"] == kind)))
        print("DRY RUN: no database changes" if args.dry_run else "Committed preview geocodes")
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--dry-run", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--force", action="store_true", help="Re-geocode every address, ignoring old coordinates (cache still reused)")
    mode.add_argument("--only-missing", action="store_true", help="Only records without a validated house/street geocode")
    parser.add_argument("--cache", default=".qa/geocode_cache.json")
    parser.add_argument("--csv", default=".qa/geocode_review.csv")
    parser.add_argument("--endpoint", default="https://nominatim.openstreetmap.org/search")
    parser.add_argument("--user-agent", default="OfficeHub-LocationReview/1.0 (one-time Manitoba property QA; https://github.com/b-mech/office-hub)")
    args = parser.parse_args()
    if not args.force and not args.only_missing:
        parser.error("Choose --force or --only-missing explicitly")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
