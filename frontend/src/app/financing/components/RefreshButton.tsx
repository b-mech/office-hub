import { RefreshCw } from "lucide-react";

export function RefreshButton({ loading, onClick }: { loading: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className="inline-flex items-center gap-2 rounded-md bg-[var(--ch-accent)] px-4 py-2 text-sm font-semibold text-[var(--ch-accent-text)] disabled:opacity-60"
    >
      <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
      Refresh from Sheet
    </button>
  );
}
