"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import { getProjects, type Lot } from "@/lib/api/costbook";
import {
  ImportApiError,
  getBoxConnectUrl,
  getBoxStatus,
  processImport,
  type BoxStatus,
  type ImportDocType,
  type ImportErrorDetail,
  type ImportResult,
} from "@/lib/api/imports";

const IMPORT_TYPES: Array<{
  title: string;
  description: string;
  docType: ImportDocType;
  accept: string;
  formats: string[];
}> = [
  {
    title: "Budgets",
    description: "Import budget templates or actuals",
    docType: "budget",
    accept: ".xlsx,.csv",
    formats: [".xlsx", ".csv"],
  },
  {
    title: "Sale OTP",
    description: "Import sale offer to purchase",
    docType: "sale_otp",
    accept: ".pdf,.docx",
    formats: [".pdf", ".docx"],
  },
  {
    title: "Land OTP",
    description: "Import land offer to purchase",
    docType: "land_otp",
    accept: ".pdf,.docx",
    formats: [".pdf", ".docx"],
  },
  {
    title: "Change Orders",
    description: "Import change order documents",
    docType: "change_order",
    accept: ".pdf,.docx,.xlsx,.csv",
    formats: [".pdf", ".docx", ".xlsx", ".csv"],
  },
];

function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function BoxConnectionCard() {
  const [status, setStatus] = useState<BoxStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getBoxStatus()
      .then((result) => {
        if (!cancelled) setStatus(result);
      })
      .catch((loadError) => {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : "Could not load Box status.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleConnect() {
    setConnecting(true);
    setError(null);
    try {
      window.location.href = await getBoxConnectUrl();
    } catch (connectError) {
      setError(connectError instanceof Error ? connectError.message : "Could not start Box connection.");
      setConnecting(false);
    }
  }

  const connected = Boolean(status?.authenticated);

  return (
    <article className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-[var(--ch-text-primary)]">Box.com</h2>
          <p className="mt-1 max-w-2xl text-sm text-[var(--ch-text-secondary)]">
            Connect your Box account to automatically file documents after generation and signing.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
            <span className="text-[var(--ch-text-secondary)]">Status:</span>
            <span
              className={`h-2.5 w-2.5 rounded-full ${
                connected ? "bg-[var(--ch-success-text)]" : "bg-[var(--ch-text-muted)]"
              }`}
            />
            <span className="font-medium text-[var(--ch-text-primary)]">
              {loading ? "Checking..." : connected ? "Connected" : "Not connected"}
            </span>
            {connected && !status?.configured && (
              <span className="text-xs text-[var(--ch-amber-text)]">
                Folder IDs still need to be added to .env
              </span>
            )}
          </div>
          {error && (
            <p className="mt-3 rounded-lg border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-3 py-2 text-sm text-[var(--ch-error-text)]">
              {error}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => void handleConnect()}
          disabled={connecting}
          className="w-fit rounded-lg bg-[var(--ch-accent)] px-4 py-2 text-sm font-bold text-[var(--ch-accent-text)] hover:bg-[var(--ch-accent-hover)] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {connecting ? "Connecting..." : connected ? "Reconnect" : "Connect Box"}
        </button>
      </div>
    </article>
  );
}

function ImportCard({ config }: { config: (typeof IMPORT_TYPES)[number] }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [processing, setProcessing] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [matchWarning, setMatchWarning] = useState<ImportErrorDetail | null>(null);
  const [projects, setProjects] = useState<Lot[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");

  async function handleProcess(matchedLotId?: string) {
    if (!file) return;
    setProcessing(true);
    setError(null);
    setResult(null);
    try {
      const importResult = await processImport(file, config.docType, { matchedLotId });
      setResult(importResult);
      setFile(null);
      setMatchWarning(null);
      setSelectedProjectId("");
      if (inputRef.current) inputRef.current.value = "";
    } catch (processError) {
      if (
        processError instanceof ImportApiError &&
        typeof processError.detail === "object" &&
        processError.detail?.code?.startsWith("budget_")
      ) {
        setMatchWarning(processError.detail);
        setError(null);
        if (projects.length === 0) {
          const projectList = await getProjects();
          setProjects(projectList);
        }
      } else {
        setError(processError instanceof Error ? processError.message : "Import failed.");
      }
    } finally {
      setProcessing(false);
    }
  }

  return (
    <article className="rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-[var(--ch-text-primary)]">{config.title}</h2>
          <p className="mt-1 text-sm text-[var(--ch-text-secondary)]">{config.description}</p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {config.formats.map((format) => (
          <span
            key={format}
            className="rounded-full border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1 text-xs text-[var(--ch-text-secondary)]"
          >
            {format}
          </span>
        ))}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept={config.accept}
        className="hidden"
        onChange={(event) => {
          setFile(event.target.files?.[0] || null);
          setError(null);
          setResult(null);
          setMatchWarning(null);
          setSelectedProjectId("");
        }}
      />

      <div className="mt-5 flex flex-col gap-3">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="w-fit rounded-lg border border-[var(--ch-accent)]/40 bg-[var(--ch-accent)]/10 px-4 py-2 text-sm font-semibold text-[var(--ch-accent)] hover:bg-[var(--ch-accent)]/15"
        >
          Upload file
        </button>

        {file && (
          <div className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-page-bg)] p-3">
            <p className="truncate text-sm font-medium text-[var(--ch-text-primary)]">{file.name}</p>
            <p className="mt-1 text-xs text-[var(--ch-text-muted)]">{fileSize(file.size)}</p>
            <button
              type="button"
              onClick={() => handleProcess()}
              disabled={processing}
              className="mt-3 inline-flex items-center gap-2 rounded-lg bg-[var(--ch-accent)] px-4 py-2 text-sm font-bold text-[var(--ch-accent-text)] hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-55"
            >
              {processing && (
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--ch-accent-text)]/30 border-t-[var(--ch-accent-text)]" />
              )}
              {processing ? "Processing..." : "Process"}
            </button>
          </div>
        )}

        {file && matchWarning && (
          <div className="rounded-lg border border-[var(--ch-amber)] bg-[var(--ch-amber-bg)] p-3 text-sm text-[var(--ch-amber-text)]">
            <p className="font-semibold">Project match required</p>
            <p className="mt-1 text-[var(--ch-amber-text)]">{matchWarning.message}</p>
            {matchWarning.search_text && (
              <p className="mt-2 truncate text-xs text-[var(--ch-text-secondary)]">Search: {matchWarning.search_text}</p>
            )}

            {matchWarning.candidates && matchWarning.candidates.length > 0 && (
              <div className="mt-3">
                <p className="mb-2 text-xs uppercase tracking-widest text-[var(--ch-text-secondary)]">Possible matches</p>
                <div className="space-y-1">
                  {matchWarning.candidates.map((candidate) => (
                    <button
                      key={candidate.id}
                      type="button"
                      onClick={() => setSelectedProjectId(candidate.id)}
                      className={`w-full rounded border px-3 py-2 text-left text-xs transition ${
                        selectedProjectId === candidate.id
                          ? "border-[var(--ch-accent)] bg-[var(--ch-accent)]/15"
                          : "border-[var(--ch-border)] bg-[var(--ch-page-bg)] hover:border-[var(--ch-accent)]/40"
                      }`}
                    >
                      <span className="block font-semibold text-[var(--ch-text-primary)]">{candidate.address}</span>
                      <span className="text-[var(--ch-text-secondary)]">{candidate.community || "Unknown community"}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="mt-3">
              <label className="mb-1.5 block text-xs uppercase tracking-widest text-[var(--ch-text-secondary)]">
                Manual project match
              </label>
              <select
                value={selectedProjectId}
                onChange={(event) => setSelectedProjectId(event.target.value)}
                className="w-full rounded-lg border border-[var(--ch-border)] bg-[var(--ch-page-bg)] px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none focus:border-[var(--ch-accent)]/60"
              >
                <option value="">Select an existing project...</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.address} - {project.community}
                  </option>
                ))}
              </select>
              {projects.length === 0 && (
                <p className="mt-2 text-xs text-[var(--ch-text-secondary)]">
                  No projects are available. Import and approve the Land OTP and Sale OTP first.
                </p>
              )}
            </div>

            <button
              type="button"
              onClick={() => handleProcess(selectedProjectId)}
              disabled={processing || !selectedProjectId}
              className="mt-3 rounded-lg bg-[var(--ch-accent)] px-4 py-2 text-sm font-bold text-[var(--ch-accent-text)] hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-55"
            >
              Import into selected project
            </button>
          </div>
        )}

        {result && (
          <div className="rounded-lg border border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] p-3 text-sm text-[var(--ch-success-text)]">
            <p className="font-semibold">Import complete</p>
            {result.resource_type === "budget" && result.budget_id ? (
              <>
                <p className="mt-1 text-[var(--ch-success-text)]/80">Draft budget ID: {result.budget_id}</p>
                <Link
                  href={`/costbook/budgets/${result.budget_id}`}
                  className="mt-2 inline-block text-[var(--ch-accent)] hover:underline"
                >
                  Open draft budget
                </Link>
              </>
            ) : (
              <>
                <p className="mt-1 text-[var(--ch-success-text)]/80">Document ID: {result.document_id}</p>
                <Link
                  href={`/documents/${result.document_id}`}
                  className="mt-2 inline-block text-[var(--ch-accent)] hover:underline"
                >
                  Open review
                </Link>
              </>
            )}
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] p-3 text-sm text-[var(--ch-error-text)]">
            {error}
          </div>
        )}
      </div>
    </article>
  );
}

export default function ImportsPage() {
  const [boxCallback] = useState(() => {
    if (typeof window === "undefined") return { connected: false, error: false };
    const params = new URLSearchParams(window.location.search);
    return {
      connected: params.get("box_connected") === "true",
      error: params.get("box_error") === "true",
    };
  });

  return (
    <div className="px-8 py-8">
      <header className="mb-6">
        <h1 className="text-3xl font-semibold tracking-tight text-[var(--ch-text-primary)]">Imports</h1>
        <p className="mt-2 text-sm text-[var(--ch-text-secondary)]">
          Upload source files and route them through Office Hub ingestion.
        </p>
      </header>

      {boxCallback.connected && (
        <div className="mb-4 rounded-xl border border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] px-4 py-3 text-sm text-[var(--ch-success-text)]">
          Box connected successfully.
        </div>
      )}

      {boxCallback.error && (
        <div className="mb-4 rounded-xl border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-4 py-3 text-sm text-[var(--ch-error-text)]">
          Box connection failed. Try reconnecting.
        </div>
      )}

      <div className="mb-4">
        <BoxConnectionCard />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {IMPORT_TYPES.map((config) => (
          <ImportCard key={config.docType} config={config} />
        ))}
      </div>
    </div>
  );
}
