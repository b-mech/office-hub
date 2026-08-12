"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { deleteDocuments, type Document, listDocuments } from "@/lib/api";

const statusOptions = ["", "received", "in_review", "approved", "rejected"];
const docTypeOptions = ["", "land_otp", "sale_otp", "invoice", "legal", "other"];

function getStatusBadge(status: string): string {
  if (status === "approved") {
    return "bg-[var(--ch-success-bg)] text-[var(--ch-success-text)] ring-[var(--ch-success-border)]";
  }
  if (status === "rejected") {
    return "bg-rose-100 text-rose-800 ring-rose-200";
  }
  if (status === "in_review") {
    return "bg-[var(--ch-warning-bg)] text-[var(--ch-warning-text)] ring-[var(--ch-warning-border)]";
  }
  return "bg-[var(--ch-surface)] text-[var(--ch-text-secondary)] ring-[var(--ch-border)]";
}

function formatDocType(docType: string): string {
  if (docType === "sale_otp") {
    return "OTP SALE";
  }
  if (docType === "land_otp") {
    return "OTP LAND";
  }
  return docType.replaceAll("_", " ");
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [status, setStatus] = useState("");
  const [docType, setDocType] = useState("");
  const [loading, setLoading] = useState(true);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectableDocuments = documents.filter(
    (document) => document.status !== "approved",
  );
  const allSelectableSelected =
    selectableDocuments.length > 0 &&
    selectableDocuments.every((document) => selectedIds.has(document.id));

  function toggleSelection(documentId: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(documentId)) {
        next.delete(documentId);
      } else {
        next.add(documentId);
      }
      return next;
    });
  }

  function closeSelectionMode() {
    setSelectionMode(false);
    setSelectedIds(new Set());
  }

  async function handleDeleteSelected() {
    if (selectedIds.size === 0) {
      return;
    }
    if (
      !window.confirm(
        `Delete ${selectedIds.size} selected document${selectedIds.size === 1 ? "" : "s"}? This cannot be undone.`,
      )
    ) {
      return;
    }

    setDeleting(true);
    setError(null);
    try {
      const response = await deleteDocuments(Array.from(selectedIds));
      const deleted = new Set(response.deleted_ids);
      setDocuments((current) =>
        current.filter((document) => !deleted.has(document.id)),
      );
      closeSelectionMode();
    } catch (deleteError) {
      setError(
        deleteError instanceof Error
          ? deleteError.message
          : "Failed to delete selected documents.",
      );
    } finally {
      setDeleting(false);
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function loadDocuments() {
      setLoading(true);
      setError(null);
      try {
        const result = await listDocuments(status || undefined, docType || undefined);
        if (!cancelled) {
          setDocuments(result);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof Error ? loadError.message : "Failed to load documents.",
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadDocuments();
    return () => {
      cancelled = true;
    };
  }, [docType, status]);

  return (
    <main className="min-h-screen bg-[var(--ch-page-bg)] px-5 py-6 text-[var(--ch-text-primary)] sm:px-8 lg:px-10">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <section className="overflow-hidden rounded-[2rem] border border-[var(--ch-border)] bg-[var(--ch-surface)] shadow-lg backdrop-blur">
          <div className="border-b border-[var(--ch-border)] px-6 py-6 sm:px-8">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-[var(--ch-text-muted)]">
              Office Hub
            </p>
            <div className="mt-3 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <h1 className="text-3xl font-semibold tracking-tight text-[var(--ch-text-primary)]">
                  Document Review Queue
                </h1>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--ch-text-secondary)]">
                  Review staged land and sale agreement documents before they cross the
                  promotion boundary into operational tables.
                </p>
              </div>
              <div className="flex items-end gap-3">
                <button
                  type="button"
                  onClick={() =>
                    selectionMode ? closeSelectionMode() : setSelectionMode(true)
                  }
                  className="mb-0.5 rounded-full border border-[var(--ch-border)] bg-white px-5 py-3 text-sm font-semibold text-[var(--ch-text-secondary)] transition hover:border-[var(--ch-border-strong)]"
                >
                  {selectionMode ? "Cancel" : "Select"}
                </button>
                <div className="grid gap-3 sm:grid-cols-2">
                <label className="flex min-w-44 flex-col gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-[var(--ch-text-muted)]">
                  Status
                  <select
                    value={status}
                    onChange={(event) => {
                      setStatus(event.target.value);
                      setSelectedIds(new Set());
                    }}
                    className="rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] px-4 py-3 text-sm font-medium normal-case tracking-normal text-[var(--ch-text-primary)] outline-none transition focus:border-[var(--ch-accent)] focus:bg-white"
                  >
                    <option value="">All statuses</option>
                    {statusOptions
                      .filter(Boolean)
                      .map((option) => (
                        <option key={option} value={option}>
                          {option.replaceAll("_", " ")}
                        </option>
                      ))}
                  </select>
                </label>
                <label className="flex min-w-44 flex-col gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-[var(--ch-text-muted)]">
                  Document Type
                  <select
                    value={docType}
                    onChange={(event) => {
                      setDocType(event.target.value);
                      setSelectedIds(new Set());
                    }}
                    className="rounded-2xl border border-[var(--ch-border)] bg-[var(--ch-surface)] px-4 py-3 text-sm font-medium normal-case tracking-normal text-[var(--ch-text-primary)] outline-none transition focus:border-[var(--ch-accent)] focus:bg-white"
                  >
                    <option value="">All types</option>
                    {docTypeOptions
                      .filter(Boolean)
                      .map((option) => (
                        <option key={option} value={option}>
                          {option.replaceAll("_", " ")}
                        </option>
                      ))}
                  </select>
                </label>
                </div>
              </div>
            </div>
          </div>

          <div className="px-3 pb-3 pt-2 sm:px-4">
            {selectionMode ? (
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-[1.25rem] border border-[var(--ch-border)] bg-white px-5 py-4 shadow-sm">
                <label className="flex items-center gap-3 text-sm font-medium text-[var(--ch-text-secondary)]">
                  <input
                    type="checkbox"
                    checked={allSelectableSelected}
                    onChange={() =>
                      setSelectedIds(
                        allSelectableSelected
                          ? new Set()
                          : new Set(selectableDocuments.map((document) => document.id)),
                      )
                    }
                    className="h-4 w-4 rounded border-[var(--ch-border)] accent-[var(--ch-accent)]"
                  />
                  Select all removable documents
                </label>
                <div className="flex items-center gap-3">
                  <span className="text-sm text-[var(--ch-text-muted)]">
                    {selectedIds.size} selected
                  </span>
                  <button
                    type="button"
                    disabled={selectedIds.size === 0 || deleting}
                    onClick={() => void handleDeleteSelected()}
                    className="rounded-full bg-rose-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {deleting ? "Deleting…" : "Delete selected"}
                  </button>
                </div>
              </div>
            ) : null}
            {loading ? (
              <div className="flex min-h-72 items-center justify-center rounded-[1.5rem] border border-dashed border-[var(--ch-border)] bg-[var(--ch-surface)]">
                <div className="flex items-center gap-3 text-sm font-medium text-[var(--ch-text-secondary)]">
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--ch-border)] border-t-[var(--ch-accent)]" />
                  Loading documents
                </div>
              </div>
            ) : error ? (
              <div className="rounded-[1.5rem] border border-rose-200 bg-rose-50 px-5 py-4 text-sm text-rose-700">
                {error}
              </div>
            ) : documents.length === 0 ? (
              <div className="flex min-h-72 flex-col items-center justify-center rounded-[1.5rem] border border-dashed border-[var(--ch-border)] bg-[var(--ch-surface)] px-6 text-center">
                <p className="text-lg font-semibold text-[var(--ch-text-primary)]">No documents found.</p>
                <p className="mt-2 max-w-md text-sm text-[var(--ch-text-secondary)]">
                  Adjust the filters or wait for the ingestion pipeline to deliver new
                  documents into the review queue.
                </p>
              </div>
            ) : (
              <div className="overflow-hidden rounded-[1.5rem] border border-[var(--ch-border)]">
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-[var(--ch-border)]">
                    <thead className="bg-[var(--ch-surface-muted)] text-left text-xs font-semibold uppercase tracking-[0.18em] text-[var(--ch-text-muted)]">
                      <tr>
                        {selectionMode ? (
                          <th className="w-14 px-5 py-4">
                            <span className="sr-only">Select</span>
                          </th>
                        ) : null}
                        <th className="px-5 py-4">Filename</th>
                        <th className="px-5 py-4">Type</th>
                        <th className="px-5 py-4">Status</th>
                        <th className="px-5 py-4">Received From</th>
                        <th className="px-5 py-4">Received At</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--ch-border)] bg-white">
                      {documents.map((document) => (
                        <tr
                          key={document.id}
                          className="transition hover:bg-[var(--ch-surface)]"
                        >
                          {selectionMode ? (
                            <td className="px-5 py-4">
                              <input
                                type="checkbox"
                                aria-label={`Select ${document.original_filename || "document"}`}
                                checked={selectedIds.has(document.id)}
                                disabled={document.status === "approved"}
                                title={
                                  document.status === "approved"
                                    ? "Approved documents are protected"
                                    : undefined
                                }
                                onChange={() => toggleSelection(document.id)}
                                className="h-4 w-4 rounded border-[var(--ch-border)] accent-[var(--ch-accent)] disabled:cursor-not-allowed disabled:opacity-30"
                              />
                            </td>
                          ) : null}
                          <td className="px-5 py-4">
                            <Link
                              href={`/documents/${document.id}`}
                              className="group flex flex-col gap-1"
                            >
                              <span className="font-medium text-[var(--ch-text-primary)] transition group-hover:text-[var(--ch-text-secondary)]">
                                {document.original_filename || "Untitled document"}
                              </span>
                              <span className="text-xs text-[var(--ch-text-muted)]">{document.id}</span>
                            </Link>
                          </td>
                          <td className="px-5 py-4 text-sm capitalize text-[var(--ch-text-secondary)]">
                            {formatDocType(document.doc_type)}
                          </td>
                          <td className="px-5 py-4">
                            <span
                              className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ring-1 ${getStatusBadge(document.status)}`}
                            >
                              {document.status.replaceAll("_", " ")}
                            </span>
                          </td>
                          <td className="px-5 py-4 text-sm text-[var(--ch-text-secondary)]">
                            {document.received_from_email || "Unknown"}
                          </td>
                          <td className="px-5 py-4 text-sm text-[var(--ch-text-secondary)]">
                            {new Date(document.received_at).toLocaleString()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
