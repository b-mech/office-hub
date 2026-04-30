-- ============================================================
-- costbook_001_initial_schema.sql
-- Creates the full costbook schema:
--   cost_categories, budgets, budget_lines,
--   vendors, purchase_orders, invoices
-- Run after all existing migrations.
-- ============================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS costbook;

-- ------------------------------------------------------------
-- 1. Cost Categories — seeded from the master budget spreadsheet
-- ------------------------------------------------------------
CREATE TABLE costbook.cost_categories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    po_number       VARCHAR(10)  NOT NULL UNIQUE,  -- e.g. "3130"
    section         VARCHAR(100) NOT NULL,          -- e.g. "Framing"
    description     TEXT         NOT NULL,
    formula_notes   TEXT,                           -- pricing rules / formulas
    sort_order      INT          NOT NULL DEFAULT 0,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------
-- 2. Budgets — one per lot, linked to land.agreements
-- ------------------------------------------------------------
CREATE TABLE costbook.budgets (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID        NOT NULL,
    lot_agreement_id    UUID,                       -- FK → land.agreements.id (nullable until linked)
    label               VARCHAR(200) NOT NULL,      -- e.g. "114 Froese"
    status              VARCHAR(20)  NOT NULL DEFAULT 'draft'
                            CHECK (status IN ('draft', 'active', 'locked')),
    sqft_main_floor     NUMERIC(10,2),
    sqft_basement       NUMERIC(10,2),
    sqft_garage         NUMERIC(10,2),
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_budgets_org_id          ON costbook.budgets(org_id);
CREATE INDEX idx_budgets_lot_agreement   ON costbook.budgets(lot_agreement_id);

-- ------------------------------------------------------------
-- 3. Budget Lines — one row per cost category per budget
-- ------------------------------------------------------------
CREATE TABLE costbook.budget_lines (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    budget_id           UUID        NOT NULL REFERENCES costbook.budgets(id) ON DELETE CASCADE,
    cost_category_id    UUID        NOT NULL REFERENCES costbook.cost_categories(id),
    estimate            NUMERIC(12,2) NOT NULL DEFAULT 0,
    actual              NUMERIC(12,2) NOT NULL DEFAULT 0,
    variance            NUMERIC(12,2) GENERATED ALWAYS AS (actual - estimate) STORED,
    origin_of_number    TEXT,                       -- who/what produced the estimate
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (budget_id, cost_category_id)
);

CREATE INDEX idx_budget_lines_budget_id ON costbook.budget_lines(budget_id);

-- ------------------------------------------------------------
-- 4. Vendors
-- ------------------------------------------------------------
CREATE TABLE costbook.vendors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID         NOT NULL,
    name            VARCHAR(200) NOT NULL,
    trade_category  VARCHAR(100),                   -- framing, electrical, plumbing …
    contact_name    VARCHAR(200),
    phone           VARCHAR(50),
    email           VARCHAR(200),
    notes           TEXT,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_vendors_org_id ON costbook.vendors(org_id);

-- ------------------------------------------------------------
-- 5. Purchase Orders
-- ------------------------------------------------------------
CREATE TABLE costbook.purchase_orders (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID         NOT NULL,
    po_number           VARCHAR(20)  NOT NULL,      -- e.g. "3130-001"
    budget_id           UUID         NOT NULL REFERENCES costbook.budgets(id),
    budget_line_id      UUID         NOT NULL REFERENCES costbook.budget_lines(id),
    vendor_id           UUID         REFERENCES costbook.vendors(id),   -- null if ad-hoc
    vendor_name_adhoc   VARCHAR(200),               -- populated when no vendor record
    description         TEXT         NOT NULL,
    amount              NUMERIC(12,2) NOT NULL,
    status              VARCHAR(20)  NOT NULL DEFAULT 'draft'
                            CHECK (status IN ('draft', 'issued', 'acknowledged', 'complete', 'cancelled')),
    issued_at           TIMESTAMPTZ,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT vendor_required CHECK (
        vendor_id IS NOT NULL OR vendor_name_adhoc IS NOT NULL
    )
);

CREATE INDEX idx_pos_org_id      ON costbook.purchase_orders(org_id);
CREATE INDEX idx_pos_budget_id   ON costbook.purchase_orders(budget_id);
CREATE INDEX idx_pos_vendor_id   ON costbook.purchase_orders(vendor_id);

-- ------------------------------------------------------------
-- 6. Invoices
-- ------------------------------------------------------------
CREATE TABLE costbook.invoices (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                  UUID          NOT NULL,
    budget_id               UUID          REFERENCES costbook.budgets(id),
    purchase_order_id       UUID          REFERENCES costbook.purchase_orders(id),
    document_id             UUID,                   -- FK → documents.documents.id
    vendor_name             TEXT,                   -- extracted by Claude
    invoice_number          TEXT,                   -- extracted
    invoice_date            DATE,                   -- extracted
    amount_claimed          NUMERIC(12,2),          -- extracted total
    line_items              JSONB,                  -- extracted line items array
    suggested_po_number     VARCHAR(10),            -- Claude's category suggestion
    extraction_confidence   FLOAT,
    status                  VARCHAR(30)  NOT NULL DEFAULT 'pending_review'
                                CHECK (status IN ('pending_review', 'approved', 'rejected')),
    approved_by             UUID,                   -- FK → users
    approved_at             TIMESTAMPTZ,
    rejection_reason        TEXT,
    notes                   TEXT,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_invoices_org_id          ON costbook.invoices(org_id);
CREATE INDEX idx_invoices_budget_id       ON costbook.invoices(budget_id);
CREATE INDEX idx_invoices_purchase_order  ON costbook.invoices(purchase_order_id);
CREATE INDEX idx_invoices_status          ON costbook.invoices(status);

-- ------------------------------------------------------------
-- 7. updated_at trigger function (reuse if already exists)
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION costbook.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_budgets_updated_at
    BEFORE UPDATE ON costbook.budgets
    FOR EACH ROW EXECUTE FUNCTION costbook.set_updated_at();

CREATE TRIGGER trg_budget_lines_updated_at
    BEFORE UPDATE ON costbook.budget_lines
    FOR EACH ROW EXECUTE FUNCTION costbook.set_updated_at();

CREATE TRIGGER trg_vendors_updated_at
    BEFORE UPDATE ON costbook.vendors
    FOR EACH ROW EXECUTE FUNCTION costbook.set_updated_at();

CREATE TRIGGER trg_purchase_orders_updated_at
    BEFORE UPDATE ON costbook.purchase_orders
    FOR EACH ROW EXECUTE FUNCTION costbook.set_updated_at();

CREATE TRIGGER trg_invoices_updated_at
    BEFORE UPDATE ON costbook.invoices
    FOR EACH ROW EXECUTE FUNCTION costbook.set_updated_at();

COMMIT;
