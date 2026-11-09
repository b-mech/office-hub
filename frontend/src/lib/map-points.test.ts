// Run with: npm run test:unit (node --experimental-strip-types --test)
import assert from "node:assert/strict";
import { test } from "node:test";
import { isValidLatLng, parseCoordinate, partitionMapRecords, planView } from "./map-points.ts";

test("parseCoordinate treats null, undefined and blank as missing", () => {
  assert.equal(parseCoordinate(null), null);
  assert.equal(parseCoordinate(undefined), null);
  assert.equal(parseCoordinate("  "), null);
});

test("parseCoordinate accepts decimal strings from Numeric columns", () => {
  assert.equal(parseCoordinate("49.861348"), 49.861348);
  assert.equal(parseCoordinate(-97.1), -97.1);
  assert.ok(Number.isNaN(parseCoordinate("abc")));
});

test("isValidLatLng rejects out-of-range values and the 0,0 sentinel", () => {
  assert.equal(isValidLatLng(49.8, -97.1), true);
  assert.equal(isValidLatLng(0, 0), false);
  assert.equal(isValidLatLng(91, 0), false);
  assert.equal(isValidLatLng(45, -181), false);
  assert.equal(isValidLatLng(Number.NaN, 1), false);
});

test("partitionMapRecords separates missing, invalid and approximate points", () => {
  const records = [
    { id: "1", label: "136 Bank Avenue", geocode_precision: "house", latitude: "49.861348", longitude: "-97.100127" },
    { id: "2", label: "No coords" },
    { id: "3", label: "Half", geocode_precision: "house", latitude: "49.9", longitude: null },
    { id: "4", label: "Zero", geocode_precision: "house", latitude: 0, longitude: 0 },
    { id: "5", label: "142 Clubhouse Drive", geocode_precision: "house", latitude: "49.895422", longitude: "-97.138515" },
    { id: "6", label: "146 Clubhouse Drive", geocode_precision: "house", latitude: "49.895422", longitude: "-97.138515" },
    { id: "7", label: "150 Clubhouse Drive", geocode_precision: "house", latitude: "49.895422", longitude: "-97.138515" },
    { id: "8", label: "311 Regent Avenue", geocode_precision: "house", latitude: "49.895337", longitude: "-97.008717" },
  ];
  const result = partitionMapRecords(records);
  assert.deepEqual(result.located.map((p) => p.record.id), ["1", "5", "6", "7", "8"]);
  assert.deepEqual(result.missing.map((r) => r.id), ["2"]);
  assert.deepEqual(result.invalid.map((r) => r.id), ["3", "4"]);
  assert.deepEqual(result.shared, []);
  assert.deepEqual(result.approximate.map((p) => p.record.id), ["5", "6", "7"]);
});

test("two validated records on one point are approximate, never exact", () => {
  const result = partitionMapRecords([
    { id: "a", label: "A", geocode_precision: "house", latitude: 49.1, longitude: -97.1 },
    { id: "b", label: "B", geocode_precision: "house", latitude: 49.1, longitude: -97.1 },
  ]);
  assert.equal(result.located.length, 2);
  assert.equal(result.shared.length, 0);
  assert.equal(result.approximate.length, 2);
});

test("planView centres one point and fits several", () => {
  assert.deepEqual(planView([]), { kind: "none" });
  assert.deepEqual(planView([{ lat: 49.8, lng: -97.1 }]), { kind: "center", lat: 49.8, lng: -97.1 });
  assert.deepEqual(planView([{ lat: 49.8, lng: -97.1 }, { lat: 49.9, lng: -97.0 }]), {
    kind: "bounds", south: 49.8, west: -97.1, north: 49.9, east: -97.0,
  });
});

 test("only validated house and street may plot; legacy and locality are hidden", () => {
  const result = partitionMapRecords([
    { id: "house", label: "A", latitude: 49.8, longitude: -97.1, geocode_precision: "house" },
    { id: "street", label: "B", latitude: 49.7, longitude: -97.0, geocode_precision: "street" },
    { id: "locality", label: "C", latitude: 49.9, longitude: -97.2, geocode_precision: "locality" },
    { id: "legacy", label: "D", latitude: 49.9, longitude: -97.3 },
  ]);
  assert.deepEqual(result.located.map((p) => p.record.id), ["house", "street"]);
  assert.deepEqual(result.approximate.map((p) => p.record.id), ["street"]);
  assert.deepEqual(result.invalid.map((r) => r.id), ["locality", "legacy"]);
});
