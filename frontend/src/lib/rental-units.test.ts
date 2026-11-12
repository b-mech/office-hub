import assert from "node:assert/strict";
import test from "node:test";

import type { RosterUnit } from "./api/rental-units.ts";
import { DEFAULT_FILTERS, filterRoster, groups, leaseFlagLabel, rosterCsv, summarize } from "./rental-units.ts";

function unit(partial: Partial<RosterUnit> & { unit_id: number }): RosterUnit {
  return {
    unit_label: "Main building", is_basement: false, unit_status: "unknown", property_id: 1,
    street_address: "1 Test St", group_name: null, city: "Winnipeg", occupancy: "vacant", lease: null,
    tenants: [], primary_tenant: null, last_lease_end: null, last_lease_status: null,
    lease_agreement_status: null, open_maintenance_tickets: 0, ...partial,
  };
}
const lease = (net: string, end: string | null, flag: RosterUnit["lease"] extends infer L ? L extends { flag: infer F } ? F : never : never = null, days: number | null = null) => ({
  id: 1, status: "active", rent: net, rent_discount: null, net_rent: net, deposit: null, lease_start: "2026-01-01",
  lease_end: end, days_to_end: days, flag,
});

const units = [
  unit({ unit_id: 1, street_address: "10 Ash Cove", unit_label: "Up", group_name: "Ash", occupancy: "occupied", tenants: ["Amy Lee"], primary_tenant: "Amy Lee", lease: lease("1800.00", "2026-12-31", "ending_soon", 49), open_maintenance_tickets: 2 }),
  unit({ unit_id: 2, street_address: "10 Ash Cove", unit_label: "Down", group_name: "Ash" }),
  unit({ unit_id: 3, street_address: "2 Gray Pl", group_name: "Gray", occupancy: "occupied", tenants: ["Bo Diaz"], primary_tenant: "Bo Diaz", lease: lease("2100.00", "2027-08-31") }),
  unit({ unit_id: 4, street_address: "=cmd", property_id: 9 }),
];

test("search matches address, unit, group and tenant names", () => {
  assert.deepEqual(filterRoster(units, { ...DEFAULT_FILTERS, query: "amy" }).map((u) => u.unit_id), [1]);
  assert.deepEqual(filterRoster(units, { ...DEFAULT_FILTERS, query: "ash down" }).map((u) => u.unit_id), [2]);
  assert.deepEqual(filterRoster(units, { ...DEFAULT_FILTERS, query: "Gray" }).map((u) => u.unit_id), [3]);
});

test("occupancy, group, property and lease filters", () => {
  assert.deepEqual(filterRoster(units, { ...DEFAULT_FILTERS, occupancy: "vacant" }).map((u) => u.unit_id), [4, 2]);
  assert.deepEqual(filterRoster(units, { ...DEFAULT_FILTERS, group: "Ash" }).map((u) => u.unit_id), [2, 1]);
  assert.deepEqual(filterRoster(units, { ...DEFAULT_FILTERS, propertyId: 9 }).map((u) => u.unit_id), [4]);
  assert.deepEqual(filterRoster(units, { ...DEFAULT_FILTERS, leaseFilter: "ending_soon" }).map((u) => u.unit_id), [1]);
});

test("sorting by rent and lease end puts vacant units last", () => {
  assert.deepEqual(filterRoster(units, { ...DEFAULT_FILTERS, sort: "rent" }).map((u) => u.unit_id), [3, 1, 4, 2]);
  assert.deepEqual(filterRoster(units, { ...DEFAULT_FILTERS, sort: "lease_end" }).map((u) => u.unit_id), [1, 3, 4, 2]);
  assert.deepEqual(filterRoster(units, { ...DEFAULT_FILTERS, sort: "tenant" }).map((u) => u.unit_id).slice(0, 2), [1, 3]);
});

test("summary counts and groups", () => {
  assert.deepEqual(summarize(units), { units: 4, occupied: 2, vacant: 2, endingSoon: 1, monthlyRent: 3900, openTickets: 2 });
  assert.deepEqual(groups(units), ["Ash", "Gray"]);
});

test("csv export escapes formulas and quotes", () => {
  const csv = rosterCsv([units[3], { ...units[0], tenants: ["Amy \"A\" Lee", "Kim, Jo"] }]);
  const lines = csv.trim().split("\n");
  assert.equal(lines[0].split(",")[0], "Address");
  assert.ok(lines[1].startsWith("'=cmd,"));
  assert.ok(lines[2].includes('"Amy ""A"" Lee; Kim, Jo"'));
});

test("lease flag labels", () => {
  assert.equal(leaseFlagLabel(units[0]), "Ends in 49 days");
  assert.equal(leaseFlagLabel(units[1]), null);
});
