import type { ReactNode } from "react";

// Counts of what is and is not on a map, so records without usable stored
// coordinates are never silently dropped.
export function MapCoverage({
  noun,
  total,
  located,
  missing,
  invalid,
  shared,
  approximate = 0,
}: {
  noun: string;
  total: number;
  located: number;
  missing: number;
  invalid: number;
  shared: number;
  approximate?: number;
}) {
  const parts: ReactNode[] = [<span key="located"><strong>{located}</strong> of {total} {noun} mapped</span>];
  if (approximate) parts.push(<span key="approximate">{approximate} approximate street pins (dashed; manual placement needed)</span>);
  if (missing) parts.push(<span key="missing">{missing} without coordinates</span>);
  if (shared) parts.push(<span key="shared" title="Several different addresses share exactly the same stored point, which is a city- or street-level geocode rather than the real location.">{shared} with approximate shared coordinates (not plotted)</span>);
  if (invalid) parts.push(<span key="invalid">{invalid} with unverified/invalid coordinates</span>);
  return (
    <p className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-[var(--ch-text-muted)]">
      {parts.map((part, index) => (
        <span key={index} className="flex gap-3">{index > 0 ? <span aria-hidden>·</span> : null}{part}</span>
      ))}
    </p>
  );
}

export type UnplottedReason = "missing" | "invalid" | "shared";

export const UNPLOTTED_LABEL: Record<UnplottedReason, string> = {
  missing: "No coordinates",
  invalid: "Invalid coordinates",
  shared: "Approximate coordinates",
};
