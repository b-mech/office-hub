"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { CONDITION_CATEGORIES, presalesApi, type FundingPartnerRule } from "@/lib/api/presales";

const NEW_RULE: FundingPartnerRule = {
  partner_code: "",
  display_name: "",
  priority: 99,
  required_docs: [],
  required_fields: [],
  disqualifying_conditions: [],
  min_quality_score: null,
  formula: null,
  max_advance_rule: null,
  package_recipient: null,
  package_docs: [],
  active: true,
};

export default function PresaleRulesPage() {
  const [rules, setRules] = useState<FundingPartnerRule[]>([]);
  const [selectedCode, setSelectedCode] = useState<string>("");
  const [draft, setDraft] = useState(() => JSON.stringify(NEW_RULE, null, 2));
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await presalesApi.rules();
      setRules(data);
      return data;
    } catch (loadError) { setError(loadError instanceof Error ? loadError.message : "Could not load partner rules"); }
    return [];
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load().then((data) => {
        if (data[0]) {
          setSelectedCode(data[0].partner_code);
          setDraft(JSON.stringify(data[0], null, 2));
        }
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const parsed = useMemo(() => {
    try { return JSON.parse(draft) as FundingPartnerRule; } catch { return null; }
  }, [draft]);

  function select(rule: FundingPartnerRule) {
    setCreating(false); setSelectedCode(rule.partner_code); setDraft(JSON.stringify(rule, null, 2)); setError(null); setNotice(null);
  }
  function startNew() { setCreating(true); setSelectedCode(""); setDraft(JSON.stringify(NEW_RULE, null, 2)); setError(null); setNotice(null); }
  function toggleCategory(category: string) {
    if (!parsed) return;
    const values = parsed.disqualifying_conditions.includes(category)
      ? parsed.disqualifying_conditions.filter((value) => value !== category)
      : [...parsed.disqualifying_conditions, category];
    setDraft(JSON.stringify({ ...parsed, disqualifying_conditions: values }, null, 2));
  }
  async function save() {
    if (!parsed) { setError("Rule JSON is invalid."); return; }
    setBusy(true); setError(null); setNotice(null);
    try {
      const saved = creating ? await presalesApi.createRule(parsed) : await presalesApi.updateRule(selectedCode, parsed);
      setCreating(false); setSelectedCode(saved.partner_code); setDraft(JSON.stringify(saved, null, 2)); setNotice("Partner rule saved; presale readiness was recomputed."); await load();
    } catch (saveError) { setError(saveError instanceof Error ? saveError.message : "Could not save rule"); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!selectedCode || !window.confirm(`Delete ${selectedCode}?`)) return;
    setBusy(true);
    try { await presalesApi.deleteRule(selectedCode); setSelectedCode(""); setCreating(false); setDraft(JSON.stringify(NEW_RULE, null, 2)); await load(); }
    catch (deleteError) { setError(deleteError instanceof Error ? deleteError.message : "Could not delete rule"); }
    finally { setBusy(false); }
  }

  return (
    <div className="px-8 py-6">
      <div className="mx-auto max-w-6xl">
        <div className="flex items-start justify-between gap-4"><div><h1 className="text-2xl font-semibold">Presale partner rules</h1><p className="mt-1 text-sm text-[var(--ch-text-muted)]">Routing, disqualifying conditions, quality thresholds, and package attachment checklists.</p></div><button onClick={startNew} className="rounded-lg bg-[var(--ch-accent)] px-4 py-2 text-sm font-semibold text-[var(--ch-accent-text)]">Add partner</button></div>
        {error ? <p className="mt-4 rounded-lg border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-3 py-2 text-sm text-[var(--ch-error-text)]">{error}</p> : null}
        {notice ? <p className="mt-4 rounded-lg border border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] px-3 py-2 text-sm text-[var(--ch-success-text)]">{notice}</p> : null}
        <div className="mt-6 grid gap-5 lg:grid-cols-[240px_1fr]">
          <aside className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-2">{rules.map((rule) => <button key={rule.partner_code} onClick={() => select(rule)} className={`mb-1 w-full rounded-lg px-3 py-3 text-left ${selectedCode === rule.partner_code && !creating ? "bg-[var(--ch-accent-soft)]" : "hover:bg-[var(--ch-surface-hover)]"}`}><strong className="text-sm">{rule.partner_code}</strong><p className="mt-1 text-xs text-[var(--ch-text-muted)]">{rule.display_name} · priority {rule.priority}</p></button>)}{!rules.length ? <p className="p-4 text-sm text-[var(--ch-text-muted)]">No rules configured.</p> : null}</aside>
          <section className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
            <h2 className="font-semibold">{creating ? "New partner" : selectedCode || "Rule editor"}</h2>
            <label className="mt-4 block text-xs font-semibold uppercase tracking-wider text-[var(--ch-text-muted)]">Disqualifying condition categories</label>
            <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{CONDITION_CATEGORIES.map((category) => <label key={category} className="flex items-center gap-2 rounded-lg border border-[var(--ch-border)] px-3 py-2 text-xs"><input type="checkbox" checked={parsed?.disqualifying_conditions.includes(category) || false} onChange={() => toggleCategory(category)} />{category.replaceAll("_", " ")}</label>)}</div>
            <label className="mt-5 block text-xs font-semibold uppercase tracking-wider text-[var(--ch-text-muted)]">Rule JSON</label>
            <textarea value={draft} onChange={(event) => setDraft(event.target.value)} rows={25} spellCheck={false} className={`mt-2 w-full rounded-lg border bg-[var(--ch-page-bg)] p-4 font-mono text-xs leading-5 outline-none ${parsed ? "border-[var(--ch-border)]" : "border-[var(--ch-error-border)]"}`} />
            <div className="mt-4 flex justify-between"><button disabled={busy || creating || !selectedCode} onClick={() => void remove()} className="rounded-lg border border-[var(--ch-error-border)] px-3 py-2 text-sm text-[var(--ch-error-text)] disabled:opacity-40">Delete</button><button disabled={busy || !parsed} onClick={() => void save()} className="rounded-lg bg-[var(--ch-accent)] px-4 py-2 text-sm font-semibold text-[var(--ch-accent-text)] disabled:opacity-40">{busy ? "Saving…" : "Save rule"}</button></div>
          </section>
        </div>
      </div>
    </div>
  );
}
