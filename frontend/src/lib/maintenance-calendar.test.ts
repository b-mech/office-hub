import assert from "node:assert/strict";
import test from "node:test";

import { validateCalendarDrop, winnipegLocalToIso } from "./maintenance-calendar.ts";

test("drag validation blocks past and completed visits", () => {
  const now = new Date("2026-10-14T18:00:00Z");
  const start = new Date("2026-10-14T17:00:00Z");
  assert.match(validateCalendarDrop({ start, end: new Date("2026-10-14T18:00:00Z"), now, visitType: "routine" })!, /future/);
  assert.match(validateCalendarDrop({ start: new Date("2026-10-15T17:00:00Z"), end: new Date("2026-10-15T18:00:00Z"), now, visitType: "routine", completed: true })!, /Completed/);
});

test("drag validation enforces the Winnipeg entry window except emergencies", () => {
  const now = new Date("2026-10-14T12:00:00Z");
  const start = new Date("2026-10-15T12:00:00Z"); // 7 AM CDT
  const end = new Date("2026-10-15T13:00:00Z");
  assert.match(validateCalendarDrop({ start, end, now, visitType: "routine" })!, /8 AM/);
  assert.equal(validateCalendarDrop({ start, end, now, visitType: "emergency" }), null);
});

test("Winnipeg wall times are converted independently of browser timezone", () => {
  assert.equal(winnipegLocalToIso("2026-07-15", "09:30"), "2026-07-15T14:30:00.000Z");
  assert.equal(winnipegLocalToIso("2026-12-15", "09:30"), "2026-12-15T15:30:00.000Z");
});
