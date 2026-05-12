"use client";

import { useRef, useState } from "react";
import Link from "next/link";

import { processImport, type ImportDocType, type ImportResult } from "@/lib/api/imports";

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

  async function handleProcess() {
    if (!file) return;
    setProcessing(true);
    setError(null);
    setResult(null);
    try {
      const importResult = await processImport(file, config.docType);
      setResult(importResult);
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (processError) {
      setError(processError instanceof Error ? processError.message : "Import failed.");
    } finally {
      setProcessing(false);
    }
  }

  return (
    <article className="rounded-xl border border-white/10 bg-white/[0.04] p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-white">{config.title}</h2>
          <p className="mt-1 text-sm text-white/50">{config.description}</p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {config.formats.map((format) => (
          <span
            key={format}
            className="rounded-full border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/45"
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
        }}
      />

      <div className="mt-5 flex flex-col gap-3">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="w-fit rounded-lg border border-[#FAC775]/40 bg-[#FAC775]/10 px-4 py-2 text-sm font-semibold text-[#FAC775] hover:bg-[#FAC775]/15"
        >
          Upload file
        </button>

        {file && (
          <div className="rounded-lg border border-white/10 bg-black/20 p-3">
            <p className="truncate text-sm font-medium text-white">{file.name}</p>
            <p className="mt-1 text-xs text-white/40">{fileSize(file.size)}</p>
            <button
              type="button"
              onClick={handleProcess}
              disabled={processing}
              className="mt-3 inline-flex items-center gap-2 rounded-lg bg-[#FAC775] px-4 py-2 text-sm font-bold text-[#0f1117] hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-55"
            >
              {processing && (
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[#0f1117]/30 border-t-[#0f1117]" />
              )}
              {processing ? "Processing..." : "Process"}
            </button>
          </div>
        )}

        {result && (
          <div className="rounded-lg border border-emerald-400/30 bg-emerald-500/10 p-3 text-sm text-emerald-100">
            <p className="font-semibold">Import complete</p>
            <p className="mt-1 text-emerald-100/80">Document ID: {result.document_id}</p>
            <Link
              href={`/documents/${result.document_id}`}
              className="mt-2 inline-block text-[#FAC775] hover:underline"
            >
              Open review
            </Link>
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-200">
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
        <h1 className="text-3xl font-semibold tracking-tight text-white">Imports</h1>
        <p className="mt-2 text-sm text-white/50">
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
