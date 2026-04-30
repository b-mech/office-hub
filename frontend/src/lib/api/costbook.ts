// lib/api/costbook.ts
// API client for costbook + lots endpoints

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `API error ${res.status}`);
  }
  return res.json();
}

// ─── Lots (from land.agreements + sales.agreements) ───────────────────────────

export interface Lot {
  id: string;
  address: string;
  lot_number?: string;
  community: string;
  buyer_name?: string;
  agreement_date?: string;
  condition_removal_date?: string;
  possession_date?: string;
  framing_date?: string;
  closing_date?: string;
  status: "active" | "possession" | "complete";
  land_agreement_id?: string;
  sale_agreement_id?: string;
}

export async function getLots(): Promise<Lot[]> {
  return apiFetch<Lot[]>("/api/v1/lots");
}

export async function getLot(id: string): Promise<Lot> {
  return apiFetch<Lot>(`/api/v1/lots/${id}`);
}

// ─── Cost Categories ──────────────────────────────────────────────────────────

export interface CostCategory {
  id: string;
  po_number: string;
  section: string;
  description: string;
  formula_notes?: string;
  sort_order: number;
  is_active: boolean;
}

export async function getCostCategories(): Promise<CostCategory[]> {
  return apiFetch<CostCategory[]>("/api/v1/costbook/cost-categories");
}

// ─── Budgets ──────────────────────────────────────────────────────────────────

export interface BudgetLine {
  id: string;
  cost_category_id: string;
  po_number: string;
  section: string;
  description: string;
  estimate: number;
  actual: number;
  variance: number;
  origin_of_number?: string;
  notes?: string;
  formula_notes?: string;
}

export interface Budget {
  id: string;
  org_id: string;
  lot_agreement_id?: string;
  label: string;
  status: "draft" | "active" | "locked";
  sqft_main_floor?: number;
  sqft_basement?: number;
  sqft_garage?: number;
  notes?: string;
  created_at: string;
  updated_at: string;
  lines: BudgetLine[];
  total_estimate: number;
  total_actual: number;
  total_variance: number;
}

export async function getBudgets(): Promise<Budget[]> {
  return apiFetch<Budget[]>("/api/v1/costbook/budgets");
}

export async function getBudget(id: string): Promise<Budget> {
  return apiFetch<Budget>(`/api/v1/costbook/budgets/${id}`);
}

export async function createBudget(data: {
  label: string;
  lot_agreement_id?: string;
  sqft_main_floor?: number;
  sqft_basement?: number;
  sqft_garage?: number;
}): Promise<Budget> {
  return apiFetch<Budget>("/api/v1/costbook/budgets", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateBudgetLine(
  budgetId: string,
  lineId: string,
  data: { estimate?: number; actual?: number; notes?: string; origin_of_number?: string }
): Promise<BudgetLine> {
  return apiFetch<BudgetLine>(`/api/v1/costbook/budgets/${budgetId}/lines/${lineId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

// ─── Vendors ──────────────────────────────────────────────────────────────────

export interface Vendor {
  id: string;
  org_id: string;
  name: string;
  trade_category?: string;
  contact_name?: string;
  phone?: string;
  email?: string;
  is_active: boolean;
}

export async function getVendors(trade_category?: string): Promise<Vendor[]> {
  const qs = trade_category ? `?trade_category=${trade_category}` : "";
  return apiFetch<Vendor[]>(`/api/v1/costbook/vendors${qs}`);
}

export async function createVendor(data: Omit<Vendor, "id" | "org_id" | "is_active">): Promise<Vendor> {
  return apiFetch<Vendor>("/api/v1/costbook/vendors", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// ─── Purchase Orders ──────────────────────────────────────────────────────────

export interface PurchaseOrder {
  id: string;
  org_id: string;
  po_number: string;
  budget_id: string;
  budget_line_id: string;
  vendor_id?: string;
  vendor_name_adhoc?: string;
  vendor_name?: string;
  description: string;
  amount: number;
  status: "draft" | "issued" | "acknowledged" | "complete" | "cancelled";
  issued_at?: string;
  notes?: string;
  created_at: string;
}

export async function getPurchaseOrders(budgetId: string): Promise<PurchaseOrder[]> {
  return apiFetch<PurchaseOrder[]>(`/api/v1/costbook/budgets/${budgetId}/purchase-orders`);
}

export async function createPurchaseOrder(
  budgetId: string,
  data: {
    budget_line_id: string;
    vendor_id?: string;
    vendor_name_adhoc?: string;
    description: string;
    amount: number;
    notes?: string;
  }
): Promise<PurchaseOrder> {
  return apiFetch<PurchaseOrder>(`/api/v1/costbook/budgets/${budgetId}/purchase-orders`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updatePoStatus(
  poId: string,
  status: PurchaseOrder["status"]
): Promise<PurchaseOrder> {
  return apiFetch<PurchaseOrder>(`/api/v1/costbook/purchase-orders/${poId}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

// ─── Invoices ─────────────────────────────────────────────────────────────────

export interface InvoiceLineItem {
  description: string;
  quantity?: number;
  unit_price?: number;
  amount: number;
}

export interface Invoice {
  id: string;
  org_id: string;
  budget_id?: string;
  purchase_order_id?: string;
  vendor_name?: string;
  invoice_number?: string;
  invoice_date?: string;
  amount_claimed?: number;
  line_items?: InvoiceLineItem[];
  suggested_po_number?: string;
  extraction_confidence?: number;
  status: "pending_review" | "approved" | "rejected";
  approved_at?: string;
  rejection_reason?: string;
  notes?: string;
  created_at: string;
}

export async function getInvoices(params?: {
  status?: string;
  budget_id?: string;
}): Promise<Invoice[]> {
  const qs = new URLSearchParams(
    Object.entries(params || {}).filter(([, v]) => v != null) as [string, string][]
  ).toString();
  return apiFetch<Invoice[]>(`/api/v1/costbook/invoices${qs ? `?${qs}` : ""}`);
}

export async function ingestInvoice(
  file: File,
  budgetId?: string,
  purchaseOrderId?: string
): Promise<Invoice> {
  const form = new FormData();
  form.append("file", file);
  if (budgetId) form.append("budget_id", budgetId);
  if (purchaseOrderId) form.append("purchase_order_id", purchaseOrderId);

  const res = await fetch(`${BASE}/api/v1/costbook/invoices/ingest`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Upload error ${res.status}`);
  }
  return res.json();
}

export async function approveInvoice(
  invoiceId: string,
  data: { budget_line_id: string; notes?: string }
): Promise<Invoice> {
  return apiFetch<Invoice>(`/api/v1/costbook/invoices/${invoiceId}/approve`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function rejectInvoice(
  invoiceId: string,
  rejection_reason: string
): Promise<Invoice> {
  return apiFetch<Invoice>(`/api/v1/costbook/invoices/${invoiceId}/reject`, {
    method: "POST",
    body: JSON.stringify({ rejection_reason }),
  });
}
