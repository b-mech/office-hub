"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApprovalReviewCard } from "./components/ApprovalReviewCard";
import { presalesApi, type ApprovalLetter, type LotOption, type PresaleDetail, type PresaleNotification, type PresaleTask } from "@/lib/api/presales";

type Tab = "board" | "review" | "unmatched";

const PACKAGE_COLUMNS = [
  ["approval_letter", "Letter"],
  ["otp_land", "OTP Land"],
  ["otp_sale", "OTP Sale"],
  ["stamped_plans", "Plans"],
  ["appraisal", "Appraisal"],
  ["prelim_budget", "Budget"],
] as const;

export default function PresalesPage() {
  const [tab, setTab] = useState<Tab>("board");
  const [board, setBoard] = useState<PresaleDetail[]>([]);
  const [letters, setLetters] = useState<ApprovalLetter[]>([]);
  const [tasks, setTasks] = useState<PresaleTask[]>([]);
  const [unmatched, setUnmatched] = useState<ApprovalLetter[]>([]);
  const [lots, setLots] = useState<LotOption[]>([]);
  const [notifications, setNotifications] = useState<PresaleNotification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [boardData, queueData, unmatchedData, lotData, notificationData] = await Promise.all([
        presalesApi.board(), presalesApi.queue(), presalesApi.unmatched(), presalesApi.lots(), presalesApi.notifications(true),
      ]);
      setBoard(boardData);
      setLetters(queueData.letters);
      setTasks(queueData.tasks);
      setUnmatched(unmatchedData);
      setLots(lotData);
      setNotifications(notificationData);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load presales");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const readinessByLot = useMemo(
    () => new Map(board.map((item) => [item.lot.id, item.readiness])),
    [board],
  );

  return (
    <main className="min-h-screen bg-[var(--ch-page-bg)] px-5 py-6 text-[var(--ch-text-primary)] md:px-8">
      <div className="mx-auto max-w-[1600px] space-y-5">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--ch-text-muted)]">Funding Queue</p>
            <h1 className="mt-1 text-2xl font-semibold">Presales</h1>
            <p className="mt-1 text-sm text-[var(--ch-text-muted)]">Approval letters, package readiness, and partner routing.</p>
          </div>
          <Link href="/settings/presales" className="rounded-lg border border-[var(--ch-border)] px-3 py-2 text-sm text-[var(--ch-text-secondary)]">Partner rules</Link>
        </header>

        <nav className="flex w-fit gap-1 rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-1">
          {(["board", "review", "unmatched"] as Tab[]).map((value) => (
            <button key={value} type="button" onClick={() => setTab(value)} className={`rounded-lg px-4 py-2 text-sm font-medium ${tab === value ? "bg-[var(--ch-accent-soft)] text-[var(--ch-accent)]" : "text-[var(--ch-text-muted)]"}`}>
              {value === "board" ? `Board (${board.length})` : value === "review" ? `Review (${letters.length})` : `Unmatched (${unmatched.length})`}
            </button>
          ))}
        </nav>

        {error ? <p className="rounded-lg border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-3 py-2 text-sm text-[var(--ch-error-text)]">{error}</p> : null}
        {notifications.length ? <section className="rounded-xl border border-[var(--ch-accent)] bg-[var(--ch-accent-soft)] p-4"><h2 className="text-sm font-semibold">Presale notifications</h2><div className="mt-2 space-y-2">{notifications.map((notification) => <div key={notification.id} className="flex flex-wrap items-center justify-between gap-3 text-sm"><span>{notification.message}</span><button type="button" onClick={() => void presalesApi.markNotificationRead(notification.id).then(load)} className="text-xs font-semibold text-[var(--ch-accent)]">Dismiss</button></div>)}</div></section> : null}
        {loading ? <p className="py-16 text-center text-sm text-[var(--ch-text-muted)]">Loading presale financing…</p> : null}

        {!loading && tab === "board" ? <PresalesBoard rows={board} /> : null}
        {!loading && tab === "review" ? (
          <div className="space-y-5">
            {letters.length === 0 ? <Empty text="No approval letters need review." /> : letters.map((letter) => (
              <ApprovalReviewCard key={letter.id} initialLetter={letter} lots={lots} readiness={letter.lot_id ? readinessByLot.get(letter.lot_id) : undefined} onChanged={load} />
            ))}
            <TaskList tasks={tasks.filter((task) => task.task_type !== "review_approval_letter")} onChanged={load} />
          </div>
        ) : null}
        {!loading && tab === "unmatched" ? (
          <div className="space-y-5">
            {unmatched.length === 0 ? <Empty text="No unmatched approval letters." /> : unmatched.map((letter) => (
              <ApprovalReviewCard key={letter.id} initialLetter={letter} lots={lots} onChanged={load} />
            ))}
          </div>
        ) : null}
      </div>
    </main>
  );
}

function PresalesBoard({ rows }: { rows: PresaleDetail[] }) {
  if (!rows.length) return <Empty text="No lots are marked presale yet." />;
  return (
    <div className="overflow-x-auto rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)]">
      <table className="min-w-[1850px] w-full border-collapse text-xs">
        <thead className="bg-[var(--ch-page-bg)] text-left uppercase tracking-wider text-[var(--ch-text-muted)]">
          <tr>
            <Header>Address</Header><Header>Realtor</Header><Header>Appraisal</Header><Header>Prelim budget</Header><Header>Bank letter</Header><Header>Lender contacted</Header>
            {PACKAGE_COLUMNS.map(([, label]) => <Header key={label}>{label}</Header>)}
            <Header>Suggested</Header><Header>Sent</Header>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const state = boardState(row);
            const letter = row.active_letter || row.letter_history[0];
            return (
              <tr key={row.lot.id} className={`border-t border-[var(--ch-border)] align-top ${rowTone(state)}`}>
                <Cell><Link href={`/financing/presales/${row.lot.id}`} className="font-semibold text-[var(--ch-accent)]">{row.lot.address}</Link><p className="mt-1 text-[var(--ch-text-muted)]">{row.buyer_names.join(", ") || "No purchaser"}</p></Cell>
                <Cell><strong>{row.lot.realtor_name || "Missing"}</strong><p className="mt-1 text-[var(--ch-text-muted)]">{row.lot.realtor_email || "Set realtor email"}</p></Cell>
                <Cell><Lifecycle item={row.package_items.appraisal} orderedLabel="Ordered" /></Cell>
                <Cell><Lifecycle item={row.package_items.prelim_budget} orderedLabel="Requested" /></Cell>
                <Cell><Lifecycle item={row.package_items.approval_letter} orderedLabel="Requested" /><p className="mt-1">Score: {letter?.quality_score ?? "—"}/10</p></Cell>
                <Cell>{letter?.lender_contacted_at ? dateText(letter.lender_contacted_at) : "—"}</Cell>
                {PACKAGE_COLUMNS.map(([name]) => <Cell key={name}><Link href={`/financing/presales/${row.lot.id}`} className={row.package_items[name]?.present ? "text-[var(--ch-success-text)]" : "text-[var(--ch-error-text)]"}>{row.package_items[name]?.present ? "✓" : "✗ Capture"}</Link></Cell>)}
                <Cell><strong>{row.readiness.suggested || "Not ready"}</strong><p className="mt-1 text-[var(--ch-text-muted)]">{state.replaceAll("_", " ")}</p></Cell>
                <Cell>{row.lot.package_sent_at ? <><strong>{row.lot.package_sent_to}</strong><p>{dateText(row.lot.package_sent_at)}</p></> : "—"}</Cell>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function TaskList({ tasks, onChanged }: { tasks: PresaleTask[]; onChanged: () => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  if (!tasks.length) return null;
  return (
    <section className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
      <h2 className="font-semibold">Open follow-up tasks</h2>
      <div className="mt-3 divide-y divide-[var(--ch-border)]">
        {tasks.map((task) => <div key={task.id} className="flex flex-wrap items-center justify-between gap-3 py-3"><div><p className="text-sm font-medium">{task.title}</p><p className="mt-1 text-xs text-[var(--ch-text-muted)]">Assigned to {String(task.payload.assignee_name || "Nicholas")} · {dateText(task.created_at)}</p></div><button type="button" disabled={busy === task.id} onClick={async () => { setBusy(task.id); try { await presalesApi.completeTask(task.id); await onChanged(); } finally { setBusy(null); } }} className="rounded-md border border-[var(--ch-border)] px-3 py-1.5 text-xs disabled:opacity-50">{busy === task.id ? "Saving…" : "Complete"}</button></div>)}
      </div>
    </section>
  );
}

function Lifecycle({ item, orderedLabel }: { item?: { requested_at: string | null; ordered_at: string | null; received_at: string | null }; orderedLabel: string }) {
  if (!item) return <>Not started</>;
  const requested = item.ordered_at || item.requested_at;
  return <><p>{requested ? `${orderedLabel}: ${dateText(requested)}` : "Not started"}</p><p className={item.received_at ? "mt-1 text-[var(--ch-success-text)]" : "mt-1 text-[var(--ch-text-muted)]"}>Received: {item.received_at ? dateText(item.received_at) : "—"}</p></>;
}

function Header({ children }: { children: React.ReactNode }) { return <th className="whitespace-nowrap px-3 py-3 font-semibold">{children}</th>; }
function Cell({ children }: { children: React.ReactNode }) { return <td className="min-w-28 px-3 py-3">{children}</td>; }
function Empty({ text }: { text: string }) { return <div className="rounded-xl border border-dashed border-[var(--ch-border)] py-16 text-center text-sm text-[var(--ch-text-muted)]">{text}</div>; }
function dateText(value: string) { return new Date(value).toLocaleDateString("en-CA", { month: "short", day: "numeric", year: "numeric" }); }
function boardState(row: PresaleDetail) {
  if (row.lot.package_sent_at) return "sent";
  if (Object.values(row.readiness.partners).some((partner) => partner.state === "disqualified")) return "disqualified";
  if (Object.values(row.readiness.partners).some((partner) => partner.state === "blocked_by_quality")) return "blocked";
  return row.readiness.suggested ? "ready" : "not_ready";
}
function rowTone(state: string) {
  if (state === "sent") return "bg-blue-500/5";
  if (state === "disqualified") return "bg-[var(--ch-error-bg)]";
  if (state === "blocked") return "bg-[var(--ch-warning-bg)]";
  if (state === "ready") return "bg-[var(--ch-success-bg)]";
  return "";
}
