import assert from "node:assert/strict";
import test from "node:test";

import {
  deriveLeaseStatus, duplicateKeys, filterMapItems, filterReports, leaseStatusLabel, leaseStatusTone, mapFiltersActive,
  propertyOptionLabel, queueEmptyMessage, queueFiltersActive, reportStatus, shortId, DEFAULT_MAP_FILTERS,
} from "./rentals-ux.ts";
import {
  activeNavHref, categoryLabel, formatDate, formatDateTime, formatMonth, formatPhone, plural, PRIORITY_ORDER, showNeedsReply, sortInspectionUnits,
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

test("one shared date, month and time format", () => {
  assert.equal(formatDate("2026-08-09"), "Aug 9, 2026");
  assert.equal(formatDate("2026-01-01"), "Jan 1, 2026"); // calendar date never shifts a day
  assert.equal(formatDate(null), "—");
  assert.equal(formatDate("not a date"), "—");
  assert.equal(formatMonth("2026-10"), "Oct 2026");
  assert.equal(formatMonth("2026-10-01"), "Oct 2026");
  assert.equal(formatDateTime("2026-08-09"), "Aug 9, 2026");
  assert.match(formatDateTime("2026-08-09T15:40:00"), /^Aug 9, 2026, 3:40\s?PM$/);
  assert.doesNotMatch(formatDate("2026-09-01"), /\d+\/\d+\/\d+/);
});

test("plural, phone and maintenance wording", () => {
  assert.equal(plural(1, "property", "properties"), "1 property");
  assert.equal(plural(3, "property", "properties"), "3 properties");
  assert.equal(plural(0, "photo"), "0 photos");
  assert.equal(formatPhone("+14313348018"), "(431) 334-8018");
  assert.equal(formatPhone("4313348018"), "(431) 334-8018");
  assert.equal(formatPhone("+442071234567"), "+442071234567");
  assert.equal(formatPhone(null), "—");
  assert.equal(categoryLabel("doors_locks_windows"), "Doors, locks & windows");
  assert.equal(categoryLabel("no_heat"), "No heat");
  assert.deepEqual([...PRIORITY_ORDER], ["low", "routine", "urgent", "emergency"]);
  assert.equal(showNeedsReply({ needs_reply: true, status: "new" }), true);
  assert.equal(showNeedsReply({ needs_reply: true, status: "closed" }), false);
  assert.equal(showNeedsReply({ needs_reply: true, status: "resolved" }), false);
  assert.equal(showNeedsReply({ needs_reply: false, status: "new" }), false);
});

test("active sidebar entry and inspection sorting", () => {
  const hrefs = ["/rentals", "/rentals/maintenance", "/rentals/units", "/lots", "/lots/timeline"];
  assert.equal(activeNavHref("/rentals/maintenance/new", hrefs), "/rentals/maintenance");
  assert.equal(activeNavHref("/rentals", hrefs), "/rentals");
  assert.equal(activeNavHref("/rentals-old", hrefs), null);
  assert.equal(activeNavHref("/lots/12", hrefs), "/lots");
  const units = [
    { street_address: "20 B St", unit_label: null, last_inspection: { inspection_date: "2026-05-01" } },
    { street_address: "3 A St", unit_label: null, last_inspection: null },
    { street_address: "10 A St", unit_label: null, last_inspection: { inspection_date: "2026-10-01" } },
  ];
  assert.deepEqual(sortInspectionUnits(units, "address").map((u) => u.street_address), ["3 A St", "10 A St", "20 B St"]);
  assert.deepEqual(sortInspectionUnits(units, "oldest_inspection").map((u) => u.street_address), ["3 A St", "20 B St", "10 A St"]);
  assert.deepEqual(sortInspectionUnits(units, "recent_inspection").map((u) => u.street_address), ["10 A St", "20 B St", "3 A St"]);
});
