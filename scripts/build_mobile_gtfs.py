#!/usr/bin/env python3
"""Build a smaller GTFS feed for the mobile BUMOG map.

The selected corridor covers Burgenland, Vienna and eastern/south-eastern
Lower Austria. A route is retained in full when at least one of its trips
serves a stop inside the corridor.
"""

from __future__ import annotations

import csv
import io
import sys
import zipfile
from pathlib import Path


# Approximate operational corridor, deliberately excluding St. Poelten,
# Waldviertel and Mostviertel. Coordinates are (longitude, latitude).
CORRIDOR = [
    (16.00, 46.70),
    (17.25, 46.70),
    (17.25, 48.18),
    (16.78, 48.18),
    (16.62, 47.98),
    (16.43, 47.82),
    (16.30, 47.58),
    (16.12, 47.28),
]

INPUT = Path(sys.argv[1] if len(sys.argv) > 1 else "gtfs.zip")
OUTPUT = Path(sys.argv[2] if len(sys.argv) > 2 else "gtfs-mobile.zip")


def inside_corridor(lon: float, lat: float) -> bool:
    inside = False
    j = len(CORRIDOR) - 1
    for i, (xi, yi) in enumerate(CORRIDOR):
        xj, yj = CORRIDOR[j]
        crosses = (yi > lat) != (yj > lat)
        if crosses:
            boundary_x = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < boundary_x:
                inside = not inside
        j = i
    return inside


def dict_rows(archive: zipfile.ZipFile, name: str):
    raw = archive.open(name)
    text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
    try:
        yield from csv.DictReader(text)
    finally:
        text.close()


def write_filtered(source, target, name, keep):
    if name not in source.namelist():
        return 0
    raw_in = source.open(name)
    text_in = io.TextIOWrapper(raw_in, encoding="utf-8-sig", newline="")
    reader = csv.DictReader(text_in)
    if not reader.fieldnames:
        text_in.close()
        return 0
    raw_out = target.open(name, "w")
    text_out = io.TextIOWrapper(raw_out, encoding="utf-8", newline="")
    writer = csv.DictWriter(text_out, fieldnames=reader.fieldnames, lineterminator="\n")
    writer.writeheader()
    count = 0
    for row in reader:
        if keep(row):
            writer.writerow(row)
            count += 1
    text_out.flush()
    text_out.close()
    text_in.close()
    return count


def copy_file(source, target, name):
    if name not in source.namelist():
        return
    with source.open(name) as src, target.open(name, "w") as dst:
        while chunk := src.read(1024 * 1024):
            dst.write(chunk)


def main():
    if not INPUT.exists():
        raise SystemExit(f"Input file not found: {INPUT}")

    with zipfile.ZipFile(INPUT) as source:
        required = {"stops.txt", "stop_times.txt", "trips.txt", "routes.txt"}
        missing = required.difference(source.namelist())
        if missing:
            raise SystemExit("Missing required GTFS files: " + ", ".join(sorted(missing)))

        regional_stops = set()
        for row in dict_rows(source, "stops.txt"):
            try:
                if inside_corridor(float(row["stop_lon"]), float(row["stop_lat"])):
                    regional_stops.add(row["stop_id"])
            except (KeyError, TypeError, ValueError):
                continue

        touching_trips = set()
        for row in dict_rows(source, "stop_times.txt"):
            if row.get("stop_id") in regional_stops:
                touching_trips.add(row.get("trip_id", ""))

        included_routes = set()
        for row in dict_rows(source, "trips.txt"):
            if row.get("trip_id") in touching_trips:
                included_routes.add(row.get("route_id", ""))

        included_trips = set()
        included_shapes = set()
        included_services = set()
        for row in dict_rows(source, "trips.txt"):
            if row.get("trip_id") in touching_trips:
                included_trips.add(row.get("trip_id", ""))
                if row.get("shape_id"):
                    included_shapes.add(row["shape_id"])
                if row.get("service_id"):
                    included_services.add(row["service_id"])

        used_stops = set()
        for row in dict_rows(source, "stop_times.txt"):
            if row.get("trip_id") in included_trips and row.get("stop_id"):
                used_stops.add(row["stop_id"])

        agency_ids = set()
        for row in dict_rows(source, "routes.txt"):
            if row.get("route_id") in included_routes and row.get("agency_id"):
                agency_ids.add(row["agency_id"])

        compression = zipfile.ZIP_DEFLATED
        with zipfile.ZipFile(OUTPUT, "w", compression=compression, compresslevel=6) as target:
            counts = {}
            counts["routes"] = write_filtered(source, target, "routes.txt", lambda r: r.get("route_id") in included_routes)
            counts["trips"] = write_filtered(source, target, "trips.txt", lambda r: r.get("trip_id") in included_trips)
            counts["stop_times"] = write_filtered(source, target, "stop_times.txt", lambda r: r.get("trip_id") in included_trips)
            counts["stops"] = write_filtered(source, target, "stops.txt", lambda r: r.get("stop_id") in used_stops)
            write_filtered(source, target, "shapes.txt", lambda r: r.get("shape_id") in included_shapes)
            write_filtered(source, target, "calendar.txt", lambda r: r.get("service_id") in included_services)
            write_filtered(source, target, "calendar_dates.txt", lambda r: r.get("service_id") in included_services)
            write_filtered(source, target, "frequencies.txt", lambda r: r.get("trip_id") in included_trips)
            write_filtered(source, target, "transfers.txt", lambda r: r.get("from_stop_id") in used_stops and r.get("to_stop_id") in used_stops)

            if agency_ids:
                write_filtered(source, target, "agency.txt", lambda r: r.get("agency_id") in agency_ids)
            else:
                copy_file(source, target, "agency.txt")

            for name in ("feed_info.txt", "attributions.txt", "levels.txt"):
                copy_file(source, target, name)

        print(
            f"Created {OUTPUT}: {counts['routes']} routes, {counts['trips']} trips, "
            f"{counts['stops']} stops, {counts['stop_times']} stop times"
        )


if __name__ == "__main__":
    main()
