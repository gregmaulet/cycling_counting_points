#!/usr/bin/env python3
"""Render merged Google Map points as an interactive Leaflet map."""

from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path


DEFAULT_INPUT = Path(__file__).with_name("merged_google_map_points_2022_2026.csv")
DEFAULT_OUTPUT = Path("test_locations_map.html")
YEARS = ("2022", "2023", "2024", "2025", "2026")


def read_points(path: Path) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            try:
                latitude = float(row.get("latitude", ""))
                longitude = float(row.get("longitude", ""))
            except ValueError:
                print(f"Skipping row {row_number}: missing or invalid coordinates")
                continue

            active_years = [year for year in YEARS if row.get(year) == "1"]
            points.append(
                {
                    "name": row.get("name", "").strip() or f"Point {row_number}",
                    "association": row.get("association", "").strip(),
                    "description": row.get("description", "").strip(),
                    "latitude": latitude,
                    "longitude": longitude,
                    "years": active_years,
                }
            )
    return points


def map_center(points: list[dict[str, object]]) -> tuple[float, float]:
    if not points:
        return 46.0, 6.0
    return (
        sum(float(point["latitude"]) for point in points) / len(points),
        sum(float(point["longitude"]) for point in points) / len(points),
    )


def build_popup(point: dict[str, object]) -> str:
    parts = [
        f"<strong>{html.escape(str(point['name']))}</strong>",
        f"<div><b>Years:</b> {html.escape(', '.join(point['years']))}</div>",
    ]
    if point["association"]:
        parts.append(f"<div><b>Association:</b> {html.escape(str(point['association']))}</div>")
    if point["description"]:
        description = html.escape(str(point["description"])).replace("\n", "<br>")
        parts.append(f"<div class=\"description\">{description}</div>")
    return "".join(parts)


def write_map(points: list[dict[str, object]], output_path: Path) -> None:
    center_latitude, center_longitude = map_center(points)
    locations = [
        {
            **point,
            "popup": build_popup(point),
        }
        for point in points
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        HTML_TEMPLATE.replace("__LOCATIONS__", json.dumps(locations, ensure_ascii=False))
        .replace("__CENTER_LAT__", f"{center_latitude:.7f}")
        .replace("__CENTER_LON__", f"{center_longitude:.7f}")
        .replace("__POINT_COUNT__", str(len(points))),
        encoding="utf-8",
    )


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Test Locations Map</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    html, body, #map {
      height: 100%;
      margin: 0;
    }
    .leaflet-popup-content {
      min-width: 220px;
    }
    .description {
      margin-top: 0.5rem;
      white-space: normal;
    }
    .summary {
      position: absolute;
      top: 12px;
      right: 12px;
      z-index: 1000;
      padding: 8px 10px;
      border-radius: 4px;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: 0 1px 4px rgba(0, 0, 0, 0.18);
      font: 14px/1.35 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="summary">__POINT_COUNT__ points</div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const locations = __LOCATIONS__;
    const map = L.map("map").setView([__CENTER_LAT__, __CENTER_LON__], 10);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors"
    }).addTo(map);

    const markers = locations.map((location) => {
      return L.marker([location.latitude, location.longitude])
        .bindPopup(location.popup)
        .addTo(map);
    });

    if (markers.length > 1) {
      const group = L.featureGroup(markers);
      map.fitBounds(group.getBounds().pad(0.12));
    }
  </script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"CSV file to read, defaults to {DEFAULT_INPUT}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"HTML file to write, defaults to {DEFAULT_OUTPUT}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    points = read_points(args.input)
    write_map(points, args.output)
    print(f"Wrote {len(points)} points to {args.output}")


if __name__ == "__main__":
    main()
