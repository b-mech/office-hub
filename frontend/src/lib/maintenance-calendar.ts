export type VisitType = "routine" | "tenant_consent" | "emergency";

function zonedParts(date: Date, timeZone = "America/Winnipeg") {
  const values = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => Number(values.find((value) => value.type === type)?.value);
  return { year: part("year"), month: part("month"), day: part("day"), hour: part("hour"), minute: part("minute") };
}

export function validateCalendarDrop(input: {
  start: Date;
  end: Date;
  now?: Date;
  visitType: VisitType;
  completed?: boolean;
}) {
  if (input.completed) return "Completed visits cannot be moved.";
  const now = input.now ?? new Date();
  if (input.start <= now) return "Visits must be scheduled in the future.";
  if (input.end <= input.start) return "The visit end time must be after its start time.";
  const start = zonedParts(input.start);
  const end = zonedParts(input.end);
  if (start.year !== end.year || start.month !== end.month || start.day !== end.day) {
    return "A visit must start and end on the same Winnipeg calendar day.";
  }
  if (input.visitType !== "emergency" && (start.hour < 8 || end.hour > 20 || (end.hour === 20 && end.minute > 0))) {
    return "Routine and tenant-consent visits must be inside the 8 AM–8 PM entry window.";
  }
  return null;
}

export function winnipegLocalToIso(dateValue: string, timeValue: string) {
  const [year, month, day] = dateValue.split("-").map(Number);
  const [hour, minute] = timeValue.split(":").map(Number);
  const target = Date.UTC(year, month - 1, day, hour, minute);
  let instant = new Date(target);
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const actual = zonedParts(instant);
    const represented = Date.UTC(actual.year, actual.month - 1, actual.day, actual.hour, actual.minute);
    instant = new Date(instant.getTime() + target - represented);
  }
  return instant.toISOString();
}

export function winnipegDateTimeFields(date: Date) {
  const part = zonedParts(date);
  return {
    date: `${part.year}-${String(part.month).padStart(2, "0")}-${String(part.day).padStart(2, "0")}`,
    time: `${String(part.hour).padStart(2, "0")}:${String(part.minute).padStart(2, "0")}`,
  };
}
