import assert from "node:assert/strict";
import test from "node:test";

import {
  checklistLabel,
  duplicateCandidates,
  filtersFromSearch,
  filtersToSearch,
  formatMoney,
  maintenanceHrefForProperty,
  parseMoney,
} from "./maintenance-workflows.ts";

const tickets = [
  { id: "1", number: "MT-00012", title: "Mice in kitchen", property: "166 Clubhouse", unit: "A", status: "in_progress" },
  { id: "2", number: "MT-00120", title: "Leaking tap", property: "45 Ash Cove", unit: "Main building", status: "new" },
  { id: "3", number: "MT-00013", title: "Mice again", property: "166 Clubhouse", unit: "A", status: "cancelled" },
  { id: "4", number: "MT-00014", title: "Dup", property: "166 Clubhouse", unit: "B", status: "duplicate" },
  { id: "5", number: "MT-00015", title: "Furnace noise", property: "166 Clubhouse", unit: "B", status: "closed" },
];

test("duplicate picker excludes self, cancelled and duplicate tickets", () => {
  assert.deepEqual(duplicateCandidates(tickets, "1", "").map((t) => t.id), ["2", "5"]);
});

test("duplicate picker ranks exact number, then prefix, then text", () => {
  assert.deepEqual(duplicateCandidates(tickets, "9", "MT-00012").map((t) => t.id), ["1"]);
  assert.deepEqual(duplicateCandidates(tickets, "9", "12").map((t) => t.id), ["1", "2"]);
  assert.deepEqual(duplicateCandidates(tickets, "9", "clubhouse").map((t) => t.id), ["1", "5"]);
  assert.deepEqual(duplicateCandidates(tickets, "9", "#MT-0012").map((t) => t.id), ["2"]);
});

test("checklist label", () => {
  assert.equal(checklistLabel({ total: 0, done: 0 }), null);
  assert.equal(checklistLabel({ total: 6, done: 2 }), "2/6 done");
  assert.equal(checklistLabel({ total: 3, done: 3 }), "Checklist done (3)");
});

test("money parsing and formatting", () => {
  assert.equal(parseMoney(""), null);
  assert.equal(parseMoney(" $1,234.5 "), "1234.5");
  assert.throws(() => parseMoney("12.345"));
  assert.throws(() => parseMoney("-4"));
  assert.equal(formatMoney("1234.5"), "$1,234.50");
  assert.equal(formatMoney(null), "—");
});

test("list filters round-trip through the URL for deep links", () => {
  const id = "0f8fad5b-d9cb-469f-a165-70867728950e";
  const parsed = filtersFromSearch(`?property_id=12&assignee_id=${id}&needs_reply=true&junk=1`);
  assert.deepEqual(parsed, { property_id: 12, assignee_id: id, needs_reply: true });
  assert.equal(filtersToSearch(parsed), `?property_id=12&assignee_id=${id}&needs_reply=true`);
  assert.deepEqual(filtersFromSearch("?property_id=abc&assignee_id=nope"), {});
  assert.equal(maintenanceHrefForProperty(7), "/rentals/maintenance?property_id=7");
});
