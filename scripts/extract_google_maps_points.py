#!/usr/bin/env python3
"""Extract and merge yearly Google My Maps point data into a CSV.

The script downloads public KML exports from Google My Maps, reads each
placemark with its enclosing Folder name as the association, then merges
locations across years.
"""

from __future__ import annotations

import argparse
import csv
import html
import math
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


MAPS = {
    2022: "1PEG41U-4mYPw05-Aqrbp-hiNmDnVwSjw",
    2023: "1EwpPSVRAuu7O905iBMLsPY0dr8upDCE",
    2024: "1yXcdC3itOhgM2sj9XfhRAGkt5rfG20s",
    2025: "18pjYfe4mFJ8LoudQ5lUgdzhU7am8KA0",
    2026: "1xDyznGWHWh2ORdkEFjVDoatprAoL0N0",
}

YEARS = tuple(MAPS)
KML_NS = {"k": "http://www.opengis.net/kml/2.2"}


@dataclass(frozen=True)
class Point:
    year: int
    name: str
    association: str
    description: str
    latitude: float
    longitude: float


@dataclass
class MergedLocation:
    points: list[Point] = field(default_factory=list)
    years: set[int] = field(default_factory=set)
    normalized_names: set[str] = field(default_factory=set)

    def add(self, point: Point) -> None:
        self.points.append(point)
        self.years.add(point.year)
        self.normalized_names.add(normalize(point.name))

    @property
    def latest_point(self) -> Point:
        return max(self.points, key=lambda p: (p.year, p.name))


def clean_text(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.strip() for line in text.split("\n") if line.strip())


def normalize(value: str) -> str:
    normalized = value.lower()
    normalized = re.sub(r"[^0-9a-zà-ÿ]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def kml_url(map_id: str) -> str:
    return f"https://www.google.com/maps/d/kml?mid={map_id}&forcekml=1"


def download_kml_files(kml_dir: Path) -> None:
    kml_dir.mkdir(parents=True, exist_ok=True)
    for year, map_id in MAPS.items():
        target = kml_dir / f"map_{year}.kml"
        print(f"Downloading {year} -> {target}")
        urllib.request.urlretrieve(kml_url(map_id), target)


def parse_extended_description(placemark: ET.Element) -> str:
    description = clean_text(placemark.findtext("k:description", default="", namespaces=KML_NS))
    extended = placemark.find("k:ExtendedData", KML_NS)
    if extended is None:
        return description

    values = {}
    for data in extended.findall("k:Data", KML_NS):
        key = clean_text(data.attrib.get("name", ""))
        value = clean_text(data.findtext("k:value", default="", namespaces=KML_NS))
        if key:
            values[key] = value

    if "description" in values:
        description = values["description"]

    extra_values = [
        f"{key}: {value}"
        for key, value in values.items()
        if key not in {"description", "nom"} and value
    ]
    return "\n".join(part for part in [description, *extra_values] if part)


def parse_folder(folder: ET.Element, year: int, inherited_association: str = "") -> list[Point]:
    association = clean_text(folder.findtext("k:name", default="", namespaces=KML_NS)) or inherited_association
    points: list[Point] = []

    for placemark in folder.findall("k:Placemark", KML_NS):
        coordinates = clean_text(
            placemark.findtext(".//k:Point/k:coordinates", default="", namespaces=KML_NS)
        )
        if not coordinates:
            continue

        longitude_text, latitude_text, *_ = coordinates.split(",")
        points.append(
            Point(
                year=year,
                name=clean_text(placemark.findtext("k:name", default="", namespaces=KML_NS)),
                association=association,
                description=parse_extended_description(placemark),
                latitude=float(latitude_text),
                longitude=float(longitude_text),
            )
        )

    for child_folder in folder.findall("k:Folder", KML_NS):
        points.extend(parse_folder(child_folder, year, association))

    return points


def parse_kml(path: Path, year: int) -> list[Point]:
    root = ET.parse(path).getroot()
    document = root.find("k:Document", KML_NS)
    if document is None:
        return []

    points: list[Point] = []
    for folder in document.findall("k:Folder", KML_NS):
        points.extend(parse_folder(folder, year))

    for placemark in document.findall("k:Placemark", KML_NS):
        coordinates = clean_text(
            placemark.findtext(".//k:Point/k:coordinates", default="", namespaces=KML_NS)
        )
        if not coordinates:
            continue
        longitude_text, latitude_text, *_ = coordinates.split(",")
        points.append(
            Point(
                year=year,
                name=clean_text(placemark.findtext("k:name", default="", namespaces=KML_NS)),
                association="",
                description=parse_extended_description(placemark),
                latitude=float(latitude_text),
                longitude=float(longitude_text),
            )
        )

    return points


def distance_meters(a: Point, b: Point) -> float:
    radius = 6_371_000
    lat1 = math.radians(a.latitude)
    lon1 = math.radians(a.longitude)
    lat2 = math.radians(b.latitude)
    lon2 = math.radians(b.longitude)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    haversine = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(haversine))


def can_merge_by_distance(point: Point, location: MergedLocation, threshold_meters: float) -> bool:
    return any(distance_meters(point, existing) <= threshold_meters for existing in location.points)


def find_merge_target(
    point: Point, locations: list[MergedLocation], threshold_meters: float
) -> MergedLocation | None:
    candidates = [location for location in locations if point.year not in location.years]
    if not candidates:
        return None

    spatial_matches = [
        location for location in candidates if can_merge_by_distance(point, location, threshold_meters)
    ]
    if spatial_matches:
        return min(
            spatial_matches,
            key=lambda location: min(distance_meters(point, existing) for existing in location.points),
        )

    point_name = normalize(point.name)
    for location in candidates:
        if point_name and point_name in location.normalized_names:
            return location

    return None


def merge_points(points: list[Point], threshold_meters: float) -> list[MergedLocation]:
    locations: list[MergedLocation] = []
    for point in sorted(points, key=lambda p: (p.year, p.name, p.latitude, p.longitude)):
        target = find_merge_target(point, locations, threshold_meters)
        if target is None:
            target = MergedLocation()
            locations.append(target)
        target.add(point)
    return locations


def format_years(years: list[int]) -> str:
    ranges: list[str] = []
    start = previous = years[0]
    for year in years[1:]:
        if year == previous + 1:
            previous = year
            continue
        ranges.append(f"{start}-{previous}" if start != previous else str(start))
        start = previous = year
    ranges.append(f"{start}-{previous}" if start != previous else str(start))
    return ",".join(ranges)


def summarize_values(points: list[Point], attr: str) -> str:
    years_by_value: dict[str, list[int]] = {}
    value_order: list[str] = []
    seen = set()
    for point in sorted(points, key=lambda p: (p.year, p.name)):
        value = getattr(point, attr)
        if not value:
            continue
        key = (point.year, value)
        if key in seen:
            continue
        seen.add(key)
        if value not in years_by_value:
            years_by_value[value] = []
            value_order.append(value)
        years_by_value[value].append(point.year)

    if not value_order:
        return ""
    if len(value_order) == 1:
        return value_order[0]
    return " | ".join(
        f"{format_years(years_by_value[value])}: {value}" for value in value_order
    )


def location_to_row(location: MergedLocation) -> dict[str, str | int]:
    latest = location.latest_point
    row: dict[str, str | int] = {
        "name": summarize_values(location.points, "name"),
        "association": summarize_values(location.points, "association"),
        "description": summarize_values(location.points, "description"),
        "latitude": f"{latest.latitude:.7f}".rstrip("0").rstrip("."),
        "longitude": f"{latest.longitude:.7f}".rstrip("0").rstrip("."),
    }
    for year in YEARS:
        row[str(year)] = 1 if year in location.years else 0
    return row


def write_csv(locations: list[MergedLocation], output_path: Path) -> None:
    fieldnames = [
        "name",
        "association",
        "description",
        "latitude",
        "longitude",
        *[str(year) for year in YEARS],
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for location in sorted(locations, key=lambda item: item.latest_point.name.lower()):
            writer.writerow(location_to_row(location))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kml-dir", type=Path, default=Path("data/kml"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("merged_google_map_points_2022_2026.csv"),
    )
    parser.add_argument(
        "--merge-distance-meters",
        type=float,
        default=35.0,
        help="Merge differently named points across years when coordinates are within this distance.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Use existing KML files from --kml-dir instead of downloading them.",
    )
    args = parser.parse_args()

    if not args.skip_download:
        download_kml_files(args.kml_dir)

    points: list[Point] = []
    for year in YEARS:
        path = args.kml_dir / f"map_{year}.kml"
        yearly_points = parse_kml(path, year)
        print(f"Parsed {len(yearly_points)} points from {path}")
        points.extend(yearly_points)

    locations = merge_points(points, args.merge_distance_meters)
    write_csv(locations, args.output)
    print(f"Wrote {len(locations)} merged rows to {args.output}")


if __name__ == "__main__":
    main()
