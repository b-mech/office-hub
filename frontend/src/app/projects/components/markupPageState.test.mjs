import assert from "node:assert/strict";
import { test } from "node:test";
import { withPageState } from "./markupPageState.ts";

test("page snapshots retain marks on other pages and replace the current page", () => {
  const first = { width: 100, height: 200, objects: [{ type: "path" }] };
  const second = { width: 100, height: 200, objects: [{ type: "rect" }] };
  const pages = withPageState(withPageState({}, 1, first), 2, second);

  assert.deepEqual(Object.keys(pages), ["1", "2"]);
  assert.deepEqual(pages["1"], first);
  assert.deepEqual(pages["2"], second);
  assert.deepEqual(withPageState(pages, 2, { ...second, objects: [] })["1"], first);
  assert.deepEqual(pages["2"], second);
});
