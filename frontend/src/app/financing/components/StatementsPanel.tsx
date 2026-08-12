import { useEffect, useState } from "react";
import {
  approveStatementDraws,
  createManualStatementSnapshot,
  getLenderStatement,
  getLenderStatements,
  getProFacilities,
  linkStatementFacility,
  retryLenderStatement,
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
  const [retrying, setRetrying] = useState(false);
  const [showManual, setShowManual] = useState(false);

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

  async function retry() {
    if (!selected) return;
    setRetrying(true);
    setError(null);
    try {
      const statement = await retryLenderStatement(selected.id);
      onSelect(statement);
      setStatements((current) =>
        current.map((item) =>
          item.id === statement.id
            ? { ...item, status: statement.status, parsed_at: statement.parsed_at }
            : item,
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not retry statement");
    } finally {
      setRetrying(false);
    }
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
                <div className="ml-auto flex gap-2">
                  <button
                    type="button"
                    onClick={() => setShowManual((current) => !current)}
                    className="rounded-md border border-[var(--ch-border)] px-2 py-1 text-xs font-semibold"
                  >
                    {showManual ? "Hide manual entry" : "Add manually"}
                  </button>
                  <button
                    type="button"
                    onClick={retry}
                    disabled={retrying}
                    className="rounded-md bg-[var(--ch-accent)] px-2 py-1 text-xs font-semibold text-[var(--ch-accent-text)] disabled:opacity-50"
                  >
                    {retrying ? "Parsing..." : "Retry parsing"}
                  </button>
                </div>
              </div>
              {typeof parseError === "string" ? (
                <p className="mb-3 rounded-md border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-3 py-2 text-sm text-[var(--ch-error-text)]">{parseError}</p>
              ) : null}
              {showManual || selected.status === "failed" ? (
                <ManualStatementEntry
                  statement={selected}
                  facilities={facilities}
                  onSaved={(statement) => {
                    onSelect(statement);
                    setShowManual(false);
                    setStatements((current) =>
                      current.map((item) =>
                        item.id === statement.id
                          ? { ...item, status: statement.status, parsed_at: statement.parsed_at }
                          : item,
                      ),
                    );
                  }}
                />
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

type ManualDraw = {
  txn_date: string;
  amount: string;
  reference: string;
};

function periodEnd(period: string): string {
  const [year, month] = period.split("-").map(Number);
  if (!year || !month) return "";
  return new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
}

function ManualStatementEntry({
  statement,
  facilities,
  onSaved,
}: {
  statement: LenderStatementDetail;
  facilities: ProFacility[];
  onSaved: (statement: LenderStatementDetail) => void;
}) {
  const [facilityId, setFacilityId] = useState("");
  const [reportedDate, setReportedDate] = useState(periodEnd(statement.period));
  const [reportedBalance, setReportedBalance] = useState("");
  const [draws, setDraws] = useState<ManualDraw[]>([]);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function updateDraw(index: number, values: Partial<ManualDraw>) {
    setDraws((current) =>
      current.map((draw, drawIndex) =>
        drawIndex === index ? { ...draw, ...values } : draw,
      ),
    );
  }

  async function save() {
    if (!facilityId || !reportedDate || !reportedBalance) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await createManualStatementSnapshot(statement.id, {
        facility_id: facilityId,
        reported_period_end_date: reportedDate,
        reported_period_end_balance: reportedBalance,
        draws: draws
          .filter((draw) => draw.txn_date && draw.amount)
          .map((draw) => ({
            txn_date: draw.txn_date,
            amount: draw.amount,
            reference: draw.reference || null,
          })),
        note: note || null,
      });
      onSaved(saved);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not save manual statement row",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mb-4 rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface-muted)] p-3">
      <h4 className="text-sm font-semibold">Manual facility entry</h4>
      <p className="mt-1 text-xs text-[var(--ch-text-muted)]">
        Use the values printed on the statement when OCR cannot recover a row.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="text-xs font-medium">
          Facility
          <select
            value={facilityId}
            onChange={(event) => setFacilityId(event.target.value)}
            className="mt-1 block w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-2 text-sm"
          >
            <option value="">Select facility</option>
            {facilities.map((facility) => (
              <option key={facility.id} value={facility.id}>
                {facility.property_name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-medium">
          Reported date
          <input
            type="date"
            value={reportedDate}
            onChange={(event) => setReportedDate(event.target.value)}
            className="mt-1 block w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-2 text-sm"
          />
        </label>
        <label className="text-xs font-medium">
          Reported balance
          <input
            inputMode="decimal"
            value={reportedBalance}
            onChange={(event) =>
              setReportedBalance(event.target.value.replace(/[$,\s]/g, ""))
            }
            placeholder="0.00"
            className="mt-1 block w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-2 text-sm"
          />
        </label>
      </div>

      {draws.length ? (
        <div className="mt-3 space-y-2">
          <p className="text-xs font-semibold">New draws on this statement</p>
          {draws.map((draw, index) => (
            <div
              key={index}
              className="grid gap-2 sm:grid-cols-[1fr_1fr_1.5fr_auto]"
            >
              <input
                type="date"
                value={draw.txn_date}
                onChange={(event) =>
                  updateDraw(index, { txn_date: event.target.value })
                }
                className="rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1.5 text-xs"
                aria-label={`Draw ${index + 1} date`}
              />
              <input
                inputMode="decimal"
                value={draw.amount}
                onChange={(event) =>
                  updateDraw(index, {
                    amount: event.target.value.replace(/[$,\s]/g, ""),
                  })
                }
                placeholder="Amount"
                className="rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1.5 text-xs"
                aria-label={`Draw ${index + 1} amount`}
              />
              <input
                value={draw.reference}
                onChange={(event) =>
                  updateDraw(index, { reference: event.target.value })
                }
                placeholder="Cheque/reference"
                className="rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1.5 text-xs"
                aria-label={`Draw ${index + 1} reference`}
              />
              <button
                type="button"
                onClick={() =>
                  setDraws((current) =>
                    current.filter((_, drawIndex) => drawIndex !== index),
                  )
                }
                className="rounded-md border border-[var(--ch-border)] px-2 py-1.5 text-xs"
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <button
          type="button"
          onClick={() =>
            setDraws((current) => [
              ...current,
              { txn_date: reportedDate, amount: "", reference: "" },
            ])
          }
          className="rounded-md border border-[var(--ch-border)] px-2 py-1.5 text-xs font-semibold"
        >
          Add draw
        </button>
        <label className="min-w-[220px] flex-1 text-xs font-medium">
          Note (optional)
          <input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            maxLength={1000}
            placeholder="Source or correction note"
            className="mt-1 block w-full rounded-md border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1.5 text-xs"
          />
        </label>
        <button
          type="button"
          onClick={save}
          disabled={saving || !facilityId || !reportedDate || !reportedBalance}
          className="rounded-md bg-[var(--ch-accent)] px-3 py-2 text-xs font-semibold text-[var(--ch-accent-text)] disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save facility row"}
        </button>
      </div>
      {error ? (
        <p className="mt-2 text-xs text-[var(--ch-error-text)]">{error}</p>
      ) : null}
    </div>
  );
}
