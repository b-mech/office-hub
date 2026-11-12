import assert from "node:assert/strict";
import { test } from "node:test";
import type { MapProperty } from "./api/rentals-map.ts";
import {
  INSPECTION_COLORS,
  OSM_ATTRIBUTION,
  OSM_MAX_NATIVE_ZOOM,
  OSM_MAX_ZOOM,
  OSM_TILE_URL,
  asCoordinate,
  isLocatedProperty,
  locatedProperties,
} from "./rentals-map-points.ts";

function property(overrides: Partial<MapProperty> = {}): MapProperty {
  return {
    property_id: 1,
    street_address: "10 Main Street",
    group_name: "Test",
    latitude: 49.895,
    longitude: -97.138,
    unit_count: 1,
    last_inspection_date: null,
    inspection_status: "current",
    ...overrides,
  };
}

test("located properties keep finite coordinates and drop nulls", () => {
  const rows = [
    property({ property_id: 1, latitude: 49.9, longitude: -97.1 }),
    property({ property_id: 2, latitude: null, longitude: -97.1 }),
    property({ property_id: 3, latitude: 49.9, longitude: null }),
    property({ property_id: 4, latitude: Number.NaN, longitude: -97.1 }),
  ];
  const located = locatedProperties(rows);
  assert.equal(located.length, 1);
  assert.equal(located[0].property_id, 1);
  assert.equal(isLocatedProperty(rows[0]), true);
  assert.equal(isLocatedProperty(rows[1]), false);
});

test("string coordinates from the map API are treated as located", () => {
  const rows = [
    property({ property_id: 5, latitude: "49.8951" as unknown as number, longitude: "-97.1383" as unknown as number }),
    property({ property_id: 6, latitude: "" as unknown as number, longitude: -97.1 }),
  ];
  const located = locatedProperties(rows);
  assert.equal(located.length, 1);
  assert.equal(located[0].property_id, 5);
  assert.equal(located[0].latitude, 49.8951);
  assert.equal(located[0].longitude, -97.1383);
  assert.equal(asCoordinate("49.8951"), 49.8951);
  assert.equal(asCoordinate(""), null);
});

test("OpenStreetMap tiles include required attribution and official tile host", () => {
  assert.equal(OSM_TILE_URL, "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png");
  assert.match(OSM_ATTRIBUTION, /OpenStreetMap/);
  assert.match(OSM_ATTRIBUTION, /https:\/\/www\.openstreetmap\.org\/copyright/);
  assert.equal(OSM_MAX_NATIVE_ZOOM, 19);
  assert.equal(OSM_MAX_ZOOM, 19);
  assert.equal(INSPECTION_COLORS.overdue, "#C62828");
});
