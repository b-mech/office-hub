"use client";

import { useRef, useState } from "react";
import Link from "next/link";

import { getProjects, type Lot } from "@/lib/api/costbook";
import {
  ImportApiError,
  processImport,
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
          <p className="mt-1 text-sm text-[var(--ch-text-muted)]">{config.description}</p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {config.formats.map((format) => (
          <span
            key={format}
            className="rounded-full border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2 py-1 text-xs text-[var(--ch-text-muted)]"
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
          className="w-fit rounded-lg border border-[var(--ch-accent)] bg-[var(--ch-accent-soft)] px-4 py-2 text-sm font-semibold text-[var(--ch-accent)] hover:bg-[var(--ch-accent-soft)]"
        >
          Upload file
        </button>

        {file && (
          <div className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] p-3">
            <p className="truncate text-sm font-medium text-[var(--ch-text-primary)]">{file.name}</p>
            <p className="mt-1 text-xs text-[var(--ch-text-muted)]">{fileSize(file.size)}</p>
            <button
              type="button"
              onClick={() => handleProcess()}
              disabled={processing}
              className="mt-3 inline-flex items-center gap-2 rounded-lg bg-[var(--ch-accent)] px-4 py-2 text-sm font-bold text-[var(--ch-accent-text)] hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-55"
            >
              {processing && (
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[color:var(--ch-accent-text)]/30 border-t-[var(--ch-accent-text)]" />
              )}
              {processing ? "Processing..." : "Process"}
            </button>
          </div>
        )}

        {file && matchWarning && (
          <div className="rounded-lg border border-[var(--ch-accent)] bg-[var(--ch-accent-soft)] p-3 text-sm text-[var(--ch-accent)]">
            <p className="font-semibold">Project match required</p>
            <p className="mt-1 text-[var(--ch-text-secondary)]">{matchWarning.message}</p>
            {matchWarning.search_text && (
              <p className="mt-2 truncate text-xs text-[var(--ch-text-muted)]">Search: {matchWarning.search_text}</p>
            )}

            {matchWarning.candidates && matchWarning.candidates.length > 0 && (
              <div className="mt-3">
                <p className="mb-2 text-xs uppercase tracking-widest text-[var(--ch-text-muted)]">Possible matches</p>
                <div className="space-y-1">
                  {matchWarning.candidates.map((candidate) => (
                    <button
                      key={candidate.id}
                      type="button"
                      onClick={() => setSelectedProjectId(candidate.id)}
                      className={`w-full rounded border px-3 py-2 text-left text-xs transition ${
                        selectedProjectId === candidate.id
                          ? "border-[var(--ch-accent)] bg-[var(--ch-accent-soft)]"
                          : "border-[var(--ch-border)] bg-[var(--ch-surface)] hover:border-[var(--ch-accent)]"
                      }`}
                    >
                      <span className="block font-semibold text-[var(--ch-text-primary)]">{candidate.address}</span>
                      <span className="text-[var(--ch-text-muted)]">{candidate.community || "Unknown community"}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="mt-3">
              <label className="mb-1.5 block text-xs uppercase tracking-widest text-[var(--ch-text-muted)]">
                Manual project match
              </label>
              <select
                value={selectedProjectId}
                onChange={(event) => setSelectedProjectId(event.target.value)}
                className="w-full rounded-lg border border-[var(--ch-border)] bg-[var(--ch-page-bg)] px-3 py-2 text-sm text-[var(--ch-text-primary)] outline-none focus:border-[var(--ch-accent)]"
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
                <p className="mt-1 text-[var(--ch-success-text)]">Draft budget ID: {result.budget_id}</p>
                <Link
                  href={`/costbook/budgets/${result.budget_id}`}
                  className="mt-2 inline-block text-[var(--ch-accent)] hover:underline"
                >
                  Open draft budget
                </Link>
              </>
            ) : (
              <>
                <p className="mt-1 text-[var(--ch-success-text)]">Document ID: {result.document_id}</p>
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
  return (
    <div className="px-8 py-8">
      <header className="mb-6">
        <h1 className="text-3xl font-semibold tracking-tight text-[var(--ch-text-primary)]">Imports</h1>
        <p className="mt-2 text-sm text-[var(--ch-text-muted)]">
          Upload source files and route them through Office Hub ingestion.
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-2">
        {IMPORT_TYPES.map((config) => (
          <ImportCard key={config.docType} config={config} />
        ))}
      </div>
    </div>
  );
}
