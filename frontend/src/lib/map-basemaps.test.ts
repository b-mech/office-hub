import assert from "node:assert/strict";
import { test } from "node:test";
import { BASEMAP_STORAGE_KEY, basemapTiles, readBasemap, resolveBasemap, saveBasemap } from "./map-basemaps.ts";
test("known query layer wins; saved preference otherwise; invalid choices use street", () => {
  assert.equal(resolveBasemap("satellite", "street"), "satellite");
  assert.equal(resolveBasemap(null, "hybrid"), "hybrid");
  assert.equal(resolveBasemap("invalid", "satellite"), "satellite");
  assert.equal(resolveBasemap(null, "__proto__"), "street");
});
test("preference persists across both map routes using the same key", () => {
  const values = new Map<string, string>();
  const storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value); } };
  assert.equal(readBasemap(storage), "street");
  assert.equal(saveBasemap(storage, "satellite"), true);
  assert.equal(values.get(BASEMAP_STORAGE_KEY), "satellite");
  assert.equal(readBasemap(storage), "satellite");
  assert.equal(readBasemap(storage, "hybrid"), "hybrid");
});
test("blocked or missing localStorage does not break layer selection", () => {
  const blocked = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("quota"); } };
  assert.equal(readBasemap(blocked), "street");
  assert.equal(readBasemap(blocked, "satellite"), "satellite");
  assert.equal(saveBasemap(blocked, "hybrid"), false);
  assert.equal(readBasemap(null), "street");
  assert.equal(saveBasemap(null, "street"), false);
});
test("satellite uses requested keyless Esri source and overzooms 19 to 20", () => {
  const layers = basemapTiles("satellite"); assert.equal(layers.length, 1);
  assert.equal(layers[0].url, "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}");
  assert.equal(layers[0].maxNativeZoom, 19); assert.equal(layers[0].maxZoom, 20);
  assert.match(layers[0].attribution, /Tiles © Esri.*Maxar.*Earthstar Geographics/);
});
test("hybrid overlays roads and labels above imagery; street has no Esri attribution", () => {
  const layers = basemapTiles("hybrid"); assert.deepEqual(layers.map((l) => l.id), ["imagery", "roads", "labels"]);
  assert.ok(layers[1].zIndex > layers[0].zIndex); assert.ok(layers[2].zIndex > layers[1].zIndex);
  assert.ok(layers.every((l) => l.maxZoom === 20 && l.url.startsWith("https://")));
  const street = basemapTiles("street"); assert.equal(street.length, 1);
  assert.match(street[0].attribution, /OpenStreetMap/); assert.doesNotMatch(street[0].attribution, /Esri/);
});
