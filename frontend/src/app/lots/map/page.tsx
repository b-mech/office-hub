"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { getLots, getProjects, type Lot } from "@/lib/api/costbook";
import { partitionMapRecords } from "@/lib/map-points";
import { EntityMap, type EntityMapMarker } from "../../components/EntityMap";
import { MapCoverage, UNPLOTTED_LABEL, type UnplottedReason } from "../../components/MapCoverage";
import { Card, Empty, ErrorNote, PageShell, fieldClass } from "../../components/WorkspaceUi";

// Land map. Records come from the tenant-enforced /api/v1/lots (land lots) and
// /api/v1/projects (active, triggered lots). Markers are drawn only from
// stored latitude/longitude on those records; there is no geocoding here.
// core.lots stores validated coordinates and geocode precision for every lot.

type Kind = "lot" | "project";
type Row = Lot & { kind: Kind; label: string };
type Filter = "all" | Kind;

const KIND_COLOR: Record<Kind, string> = { lot: "#8A6D1F", project: "rgb(23 105 140)" };
const KIND_LABEL: Record<Kind, string> = { lot: "Land lot", project: "Active project" };
const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "lot", label: "Land lots" },
  { key: "project", label: "Projects" },
];

const recordHref = (row: Row) => (row.kind === "project" ? `/projects/${row.id}` : `/lots?project=${row.id}`);
const errorMessage = (reason: unknown, fallback: string) => (reason instanceof Error ? reason.message : fallback);

export default function LotsMapPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    Promise.allSettled([getLots(), getProjects()]).then(([lotsResult, projectsResult]) => {
      const next: Row[] = [];
      const failures: string[] = [];
      if (lotsResult.status === "fulfilled") {
        // Cancelled lots are history, not locations to visit.
        lotsResult.value.filter((lot) => !lot.cancelled).forEach((lot) => next.push({ ...lot, kind: "lot", label: lot.address }));
      } else failures.push(`Lots: ${errorMessage(lotsResult.reason, "unavailable")}`);
      if (projectsResult.status === "fulfilled") {
        projectsResult.value.forEach((lot) => next.push({ ...lot, kind: "project", label: lot.address }));
      } else failures.push(`Projects: ${errorMessage(projectsResult.reason, "unavailable")}`);
      setRows(next);
      setErrors(failures);
    });
  }, []);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (rows ?? []).filter(
      (row) =>
        (filter === "all" || row.kind === filter) &&
        (!q || `${row.address} ${row.community} ${row.lot_number ?? ""} ${row.buyer_name ?? ""} ${row.client_name ?? ""}`.toLowerCase().includes(q)),
    );
  }, [rows, filter, query]);

  const partition = useMemo(() => partitionMapRecords(rows ?? []), [rows]);
  const visibleIds = useMemo(() => new Set(visible.map((row) => row.id)), [visible]);
  const reasonById = useMemo(() => {
    const reasons = new Map<string, UnplottedReason>();
    partition.missing.forEach((row) => reasons.set(row.id, "missing"));
    partition.invalid.forEach((row) => reasons.set(row.id, "invalid"));
    partition.shared.forEach((row) => reasons.set(row.id, "shared"));
    return reasons;
  }, [partition]);

  const markers = useMemo<EntityMapMarker[]>(
    () =>
      partition.located
        .filter((point) => visibleIds.has(point.record.id))
        .map(({ record, lat, lng, approximate }) => ({
          approximate,
          id: record.id,
          lat,
          lng,
          title: record.address,
          lines: [`${KIND_LABEL[record.kind]} · ${record.community}`, record.lot_number ? `Lot ${record.lot_number}` : "", record.client_name ?? record.buyer_name ?? ""],
          href: recordHref(record),
          linkLabel: record.kind === "project" ? "Open project" : "Open lot",
          color: KIND_COLOR[record.kind],
        })),
    [partition, visibleIds],
  );

  const approximateIds = new Set(partition.approximate.map((point) => point.record.id));
  const total = rows?.length ?? 0;

  return (
    <PageShell
      title="Land map"
      subtitle="Lots and active projects at their stored coordinates"
      actions={<div className="flex gap-2 text-xs"><Link className="rounded-md border border-[var(--ch-border)] px-3 py-2" href="/land">Overview</Link><Link className="rounded-md border border-[var(--ch-border)] px-3 py-2" href="/lots">Lots</Link></div>}
    >
      {errors.map((message) => <ErrorNote key={message} message={message} />)}
      {!rows ? <p className="text-sm text-[var(--ch-text-muted)]">Loading…</p> : null}
      {rows ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <MapCoverage
              noun="lots and projects"
              total={total}
              located={partition.located.length}
              missing={partition.missing.length}
              invalid={partition.invalid.length}
              shared={partition.shared.length}
              approximate={partition.approximate.length}
            />
            <div className="flex w-full flex-wrap gap-2 sm:w-auto">
              <div className="flex gap-1" role="group" aria-label="Show">
                {FILTERS.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    aria-pressed={filter === option.key}
                    onClick={() => setFilter(option.key)}
                    className={`rounded-md border px-3 py-2 text-xs ${filter === option.key ? "border-[var(--ch-accent)] bg-[var(--ch-accent-soft)] font-semibold" : "border-[var(--ch-border)]"}`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className={`${fieldClass} min-w-0 flex-1 sm:w-64`}
                placeholder="Search address, community, client"
                aria-label="Search lots and projects"
              />
            </div>
          </div>
          {partition.located.length > 0 ? (
            <EntityMap markers={markers} selectedId={selectedId} onSelect={setSelectedId} ariaLabel="Lots and projects map" />
          ) : (
            <Empty>
              No validated house or street coordinates are available for these records.
              Locations are not guessed from addresses. Every lot and project is listed below.
            </Empty>
          )}
          <Card title={`${filter === "all" ? "Lots and projects" : filter === "lot" ? "Land lots" : "Projects"} · ${visible.length}`}>
            {visible.length === 0 ? <Empty>Nothing matches.</Empty> : (
              <ul className="divide-y divide-[var(--ch-border)]">
                {visible.map((row) => {
                  const reason = reasonById.get(row.id);
                  return (
                    <li key={`${row.kind}-${row.id}`} className={`flex flex-wrap items-center gap-3 py-2 text-sm ${selectedId === row.id ? "bg-[var(--ch-accent-soft)]" : ""}`}>
                      <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: KIND_COLOR[row.kind] }} aria-hidden />
                      <div className="min-w-0 flex-1">
                        <Link href={recordHref(row)} className="font-medium hover:text-[var(--ch-accent)]">{row.address}</Link>
                        <p className="text-xs text-[var(--ch-text-muted)]">
                          {[KIND_LABEL[row.kind], row.community, row.lot_number ? `Lot ${row.lot_number}` : null, row.client_name ?? row.buyer_name].filter(Boolean).join(" · ")}
                        </p>
                      </div>
                      {reason ? (
                        <span className="rounded-full border border-[var(--ch-border)] px-2 py-1 text-xs text-[var(--ch-text-muted)]">{UNPLOTTED_LABEL[reason]}</span>
                      ) : (
                        <button type="button" onClick={() => setSelectedId(row.id)} className="rounded-md border border-[var(--ch-border)] px-2 py-1 text-xs hover:border-[var(--ch-border-strong)]">
                          {approximateIds.has(row.id) ? "Approximate street pin · review" : "Show on map"}
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </div>
      ) : null}
    </PageShell>
  );
}
