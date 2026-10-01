const monthNumbers: Record<string, string> = {
  jan: "01",
  feb: "02",
  mar: "03",
  apr: "04",
  may: "05",
  jun: "06",
  jul: "07",
  aug: "08",
  sep: "09",
  oct: "10",
  nov: "11",
  dec: "12",
};

export function defaultStatementPeriod(now = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  return `${now.getFullYear()}-${month}`;
}

export function inferStatementPeriod(filename: string, now = new Date()): string {
  const iso = filename.match(/\b(20\d{2})[-_. ](0[1-9]|1[0-2])\b/);
  if (iso) return `${iso[1]}-${iso[2]}`;

  const lower = filename.toLowerCase();
  const monthMatch = lower.match(/\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b/);
  const yearMatch = filename.match(/(20\d{2})/);
  if (monthMatch && yearMatch) {
    return `${yearMatch[1]}-${monthNumbers[monthMatch[1].slice(0, 3)]}`;
  }

  const compactDate = filename.match(/\b\d{2}(\d{2})(20\d{2})\b/);
  if (compactDate && Number(compactDate[1]) >= 1 && Number(compactDate[1]) <= 12) {
    return `${compactDate[2]}-${compactDate[1]}`;
  }
  return defaultStatementPeriod(now);
}
