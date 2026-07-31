"use client";

import { useEffect, useMemo, useState } from "react";
import { getFinancingDashboard, refreshFinancingFromSheet } from "@/lib/api/financing";
import type { FinancingDashboard, FinancingProperty, LenderStatementDetail, LenderType } from "@/types/financing";
import { FilterBar, type FinancingFilters } from "./components/FilterBar";
import { FinancingStatementImport } from "./components/FinancingStatementImport";
import { LenderSummaryCards } from "./components/LenderSummaryCards";
import { MasterPropertyDrawTable } from "./components/MasterPropertyDrawTable";
import { MasterSummaryBar } from "./components/MasterSummaryBar";
import { PropertyDetailDrawer } from "./components/PropertyDetailDrawer";
import { RefreshButton } from "./components/RefreshButton";
import { StatementsPanel } from "./components/StatementsPanel";

const emptyFilters: FinancingFilters = {
  lender: null,
  soldOrSpec: "ALL",
  stages: [],
  possessionFrom: "",
  possessionTo: "",
  search: "",
};

export default function FinancingPage() {
  const [dashboard, setDashboard] = useState<FinancingDashboard | null>(null);
  const [filters, setFilters] = useState<FinancingFilters>(emptyFilters);
  const [selected, setSelected] = useState<FinancingProperty | null>(null);
  const [selectedStatement, setSelectedStatement] = useState<LenderStatementDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    const data = await getFinancingDashboard();
    setDashboard(data);
    if (selected) {
      setSelected(data.properties.find((item) => item.property_id === selected.property_id) || null);
    }
  }

  useEffect(() => {
    let active = true;
    getFinancingDashboard()
      .then((data) => {
        if (active) {
          setDashboard(data);
          const requestedPropertyId = new URLSearchParams(window.location.search).get("property_id");
          if (requestedPropertyId) {
            setSelected(data.properties.find((item) => item.property_id === requestedPropertyId) || null);
          }
        }
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Failed to load financing dashboard");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const filtered = useMemo(() => {
    const source = dashboard?.properties || [];
    return source.filter((item) => {
      if (filters.lender && item.lender_type !== filters.lender) return false;
      if (filters.soldOrSpec !== "ALL" && (item.sold_or_spec || "").toUpperCase() !== filters.soldOrSpec) return false;
      if (filters.stages.length && !filters.stages.includes((item.stage || "").toUpperCase())) return false;
      if (filters.possessionFrom && (!item.possession_date || item.possession_date < filters.possessionFrom)) return false;
      if (filters.possessionTo && (!item.possession_date || item.possession_date > filters.possessionTo)) return false;
      if (filters.search && !item.address.toLowerCase().includes(filters.search.toLowerCase())) return false;
      return true;
    });
  }, [dashboard, filters]);

  async function refresh() {
    setSyncing(true);
    setNotice(null);
    setError(null);
    try {
      const result = await refreshFinancingFromSheet();
      await load();
      setNotice(`Synced ${result.synced} rows; created ${result.created_properties} properties${result.errors.length ? `; ${result.errors.length} errors` : ""}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sheet sync failed");
    } finally {
      setSyncing(false);
    }
  }

  function setLender(lender: LenderType | null) {
    setFilters((current) => ({ ...current, lender }));
  }

  if (loading) {
    return <div className="min-h-screen bg-[var(--ch-page-bg)] p-8 text-sm text-[var(--ch-text-muted)]">Loading financing dashboard...</div>;
  }

  return (
    <main className="min-h-screen bg-[var(--ch-page-bg)] px-5 py-6 text-[var(--ch-text-primary)] md:px-8">
      <div className="mx-auto max-w-7xl space-y-5">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold">Financing Dashboard</h1>
            <p className="mt-1 text-sm text-[var(--ch-text-muted)]">
              Last synced {dashboard?.last_synced_at ? new Date(dashboard.last_synced_at).toLocaleString() : "never"}
            </p>
          </div>
          <div className="flex flex-wrap items-start justify-end gap-2">
            <FinancingStatementImport onImported={load} onStatement={setSelectedStatement} />
            <RefreshButton loading={syncing} onClick={refresh} />
          </div>
        </header>

        {notice ? <p className="rounded-md border border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] px-3 py-2 text-sm text-[var(--ch-success-text)]">{notice}</p> : null}
        {error ? <p className="rounded-md border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-3 py-2 text-sm text-[var(--ch-error-text)]">{error}</p> : null}

        <MasterSummaryBar properties={dashboard?.properties || []} />
        {dashboard ? <LenderSummaryCards summary={dashboard.summary} active={filters.lender} onSelect={setLender} /> : null}
        <FilterBar filters={filters} onChange={setFilters} onClear={() => setFilters(emptyFilters)} />
        <MasterPropertyDrawTable properties={filtered} onSelect={setSelected} />
        <StatementsPanel selected={selectedStatement} onSelect={setSelectedStatement} />
      </div>
      <PropertyDetailDrawer property={selected} properties={dashboard?.properties || []} onClose={() => setSelected(null)} onUpdated={load} />
    </main>
  );
}
