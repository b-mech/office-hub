import assert from "node:assert/strict";
import test from "node:test";

import {
  deriveLeaseStatus, duplicateKeys, filterMapItems, filterReports, leaseStatusLabel, leaseStatusTone, mapFiltersActive,
  propertyOptionLabel, queueEmptyMessage, queueFiltersActive, reportStatus, shortId, DEFAULT_MAP_FILTERS,
} from "./rentals-ux.ts";

test("lease status labels and tones", () => {
  assert.equal(leaseStatusLabel("month_to_month"), "Month to month");
  assert.equal(leaseStatusLabel("expired"), "Expired");
  assert.equal(leaseStatusLabel(null), "—");
  assert.equal(leaseStatusTone("expired"), "error");
  assert.equal(leaseStatusTone("upcoming"), "info");
  assert.equal(leaseStatusTone("active"), "success");
});

test("deriveLeaseStatus mirrors the server rule", () => {
  const today = "2026-11-13";
  assert.equal(deriveLeaseStatus("active", "2026-10-08", "2026-11-07", today), "expired");
  assert.equal(deriveLeaseStatus("active", "2026-12-01", null, today), "upcoming");
  assert.equal(deriveLeaseStatus("active", "2020-12-01", null, today), "active");
  assert.equal(deriveLeaseStatus("month_to_month", "2020-01-01", "2021-01-01", today), "month_to_month");
  assert.equal(deriveLeaseStatus("expired", "2023-06-01", "2024-05-31", today), "expired");
});

test("duplicate addresses get an ID suffix, unique ones do not", () => {
  const props = [
    { id: 1, address: "166 Clubhouse Drive", name: "Lorette" },
    { id: 12, address: "166 Clubhouse Drive ", name: "Lorette" },
    { id: 6, address: "142 Clubhouse Drive", name: "Lorette" },
  ];
  const dups = duplicateKeys(props, (p) => p.address);
  assert.deepEqual([...dups], ["166 clubhouse drive"]);
  assert.equal(propertyOptionLabel(props[0], dups), "166 Clubhouse Drive · Lorette · #1");
  assert.equal(propertyOptionLabel(props[1], dups), "166 Clubhouse Drive  · Lorette · #12");
  assert.equal(propertyOptionLabel(props[2], dups), "142 Clubhouse Drive · Lorette");
  assert.equal(propertyOptionLabel({ id: 4, name: "Only name" }, new Set()), "Only name");
});

test("map filters by query, group and inspection status", () => {
  const items = [
    { street_address: "1 Ash", group_name: "Ash", inspection_status: "due", company_name: "PRIVI" },
    { street_address: "2 Gray", group_name: "Gray", inspection_status: "never", company_name: "Lease Agreement Test" },
  ];
  assert.equal(filterMapItems(items, { ...DEFAULT_MAP_FILTERS, group: "Gray" }).length, 1);
  assert.equal(filterMapItems(items, { ...DEFAULT_MAP_FILTERS, status: "due" })[0].street_address, "1 Ash");
  assert.equal(filterMapItems(items, { ...DEFAULT_MAP_FILTERS, query: "agreement test" }).length, 1);
  assert.equal(mapFiltersActive(DEFAULT_MAP_FILTERS), false);
  assert.equal(mapFiltersActive({ ...DEFAULT_MAP_FILTERS, status: "never" }), true);
});

test("reports: expired status, search and sort", () => {
  const now = new Date("2026-11-13T12:00:00Z");
  const reports = [
    { id: "aaaa1111-0000-0000-0000-000000000000", title: "Rental Inspection Report", status: "sent", expires_at: "2026-11-01T00:00:00Z", created_at: "2026-10-25T00:00:00Z", items: [{ address: "1 Ash" }] },
    { id: "bbbb2222-0000-0000-0000-000000000000", title: "Rental Inspection Report", status: "draft", expires_at: "2026-11-20T00:00:00Z", created_at: "2026-11-12T00:00:00Z", items: [{ address: "2 Gray" }] },
    { id: "cccc3333-0000-0000-0000-000000000000", title: "Lorette spring", status: "sent", expires_at: "2026-11-18T00:00:00Z", created_at: "2026-11-01T00:00:00Z", items: [{ address: "166 Clubhouse Drive" }] },
  ];
  assert.equal(reportStatus(reports[0], now), "expired");
  assert.equal(reportStatus(reports[1], now), "draft");
  assert.equal(shortId(reports[0].id), "aaaa1111");
  assert.deepEqual(filterReports(reports, "", "newest", "", now).map((r) => r.id[0]), ["b", "c", "a"]);
  assert.deepEqual(filterReports(reports, "", "oldest", "", now).map((r) => r.id[0]), ["a", "c", "b"]);
  assert.deepEqual(filterReports(reports, "", "expires", "", now).map((r) => r.id[0]), ["a", "c", "b"]);
  assert.deepEqual(filterReports(reports, "clubhouse", "newest", "", now).map((r) => r.id[0]), ["c"]);
  assert.deepEqual(filterReports(reports, "bbbb2222", "newest", "", now).map((r) => r.id[0]), ["b"]);
  assert.deepEqual(filterReports(reports, "", "newest", "expired", now).map((r) => r.id[0]), ["a"]);
});

test("maintenance empty state distinguishes no tickets from filtered out", () => {
  assert.equal(queueFiltersActive({}, ""), false);
  assert.equal(queueFiltersActive({ include_terminal: true }, ""), false);
  assert.equal(queueFiltersActive({ priority: "low" }, ""), true);
  assert.equal(queueFiltersActive({}, " leak "), true);
  assert.equal(queueEmptyMessage({ priority: "low" }, "").canReset, true);
  assert.match(queueEmptyMessage({}, "").title, /No open tickets/);
  assert.match(queueEmptyMessage({ include_terminal: true }, "").title, /No maintenance tickets yet/);
});
