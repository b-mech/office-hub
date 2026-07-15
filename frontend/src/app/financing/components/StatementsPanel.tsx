import { useEffect, useState } from "react";
import {
  approveStatementDraws,
  getLenderStatement,
  getLenderStatements,
  getProFacilities,
  linkStatementFacility,
} from "@/lib/api/financing";
import type { LenderStatement, LenderStatementDetail, ProFacility } from "@/types/financing";

const money = new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD" });

function num(value: unknown): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function chip(status: string): string {
  if (status === "matched" || status === "parsed") return "bg-[var(--ch-success-bg)] text-[var(--ch-success-text)]";
  if (status === "failed" || status === "balance_mismatch") return "bg-[var(--ch-error-bg)] text-[var(--ch-error-text)]";
  return "bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)]";
}

export function StatementsPanel({ selected, onSelect }: { selected: LenderStatementDetail | null; onSelect: (statement: LenderStatementDetail | null) => void }) {
  const [statements, setStatements] = useState<LenderStatement[]>([]);
  const [facilities, setFacilities] = useState<ProFacility[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [statementRows, facilityRows] = await Promise.all([getLenderStatements("PRO"), getProFacilities()]);
      setStatements(statementRows);
      setFacilities(facilityRows);
      if (selected) {
        onSelect(await getLenderStatement(selected.id));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load statements");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let active = true;
    Promise.all([getLenderStatements("PRO"), getProFacilities()])
      .then(async ([statementRows, facilityRows]) => {
        if (!active) return;
        setStatements(statementRows);
        setFacilities(facilityRows);
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Could not load statements");
      });
    return () => {
      active = false;
    };
  }, [selected?.id]);

  async function open(statement: LenderStatement) {
    onSelect(await getLenderStatement(statement.id));
  }

  async function approve(snapshotId: string) {
    await approveStatementDraws(snapshotId);
    if (selected) onSelect(await getLenderStatement(selected.id));
  }

  async function link(snapshotId: string, facilityId: string) {
    if (!facilityId) return;
    await linkStatementFacility(snapshotId, facilityId);
    if (selected) onSelect(await getLenderStatement(selected.id));
  }

  const parseError = selected?.parse_payload?.error;

  return (
    <section className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">Statements</h2>
        <button onClick={load} className="rounded-md border border-[var(--ch-border)] px-3 py-1.5 text-xs font-semibold" type="button">
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>
      {error ? <p className="mb-3 text-sm text-[var(--ch-error-text)]">{error}</p> : null}
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <div className="space-y-2">
          {statements.length === 0 ? <p className="text-sm text-[var(--ch-text-muted)]">No statements imported yet.</p> : null}
          {statements.map((statement) => (
            <button
              type="button"
              key={statement.id}
              onClick={() => open(statement)}
              className={`w-full rounded-md border p-3 text-left text-sm ${selected?.id === statement.id ? "border-[var(--ch-accent)]" : "border-[var(--ch-border)]"}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">{statement.lender} {statement.period}</span>
                <span className={`rounded-full px-2 py-0.5 text-xs ${chip(statement.status)}`}>{statement.status}</span>
              </div>
              <p className="mt-1 truncate text-xs text-[var(--ch-text-muted)]">{statement.original_filename || statement.minio_object_key}</p>
            </button>
          ))}
        </div>
        <div>
          {!selected ? <p className="text-sm text-[var(--ch-text-muted)]">Select a statement to inspect reconciliation.</p> : null}
          {selected ? (
            <div>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <h3 className="font-semibold">{selected.original_filename || selected.minio_object_key}</h3>
                <span className={`rounded-full px-2 py-0.5 text-xs ${chip(selected.status)}`}>{selected.status}</span>
              </div>
              {typeof parseError === "string" ? (
                <p className="mb-3 rounded-md border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-3 py-2 text-sm text-[var(--ch-error-text)]">{parseError}</p>
              ) : null}
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead className="text-xs uppercase text-[var(--ch-text-muted)]">
                    <tr>
                      {["Facility", "Status", "Reported", "Computed", "Delta", "Actions"].map((head) => (
                        <th key={head} className="px-2 py-2 text-left font-semibold">{head}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {selected.snapshots.map((snapshot) => (
                      <tr key={snapshot.id} className="border-t border-[var(--ch-border)]">
                        <td className="px-2 py-2">{snapshot.matched_property_name}</td>
                        <td className="px-2 py-2"><span className={`rounded-full px-2 py-0.5 text-xs ${chip(snapshot.reconciliation_status)}`}>{snapshot.reconciliation_status}</span></td>
                        <td className="px-2 py-2 text-right tabular-nums">{money.format(num(snapshot.reported_period_end_balance))}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{snapshot.computed_balance == null ? "-" : money.format(num(snapshot.computed_balance))}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{snapshot.delta == null ? "-" : money.format(num(snapshot.delta))}</td>
                        <td className="px-2 py-2">
                          {snapshot.new_draws_detected?.length ? (
                            <button type="button" onClick={() => approve(snapshot.id)} className="rounded-md bg-[var(--ch-accent)] px-2 py-1 text-xs font-semibold text-[var(--ch-accent-text)]">
                              Approve {snapshot.new_draws_detected.length}
                            </button>
                          ) : null}
                          {!snapshot.facility_id ? (
                            <select onChange={(event) => link(snapshot.id, event.target.value)} className="ml-2 rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1 text-xs" defaultValue="">
                              <option value="">Link facility</option>
                              {facilities.map((facility) => (
                                <option key={facility.id} value={facility.id}>{facility.property_name}</option>
                              ))}
                            </select>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
