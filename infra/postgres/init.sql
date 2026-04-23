-- Office Hub Database Schema
-- Four schemas: core, documents, land, sales
-- Money: NUMERIC(15,2) throughout
-- PKs: UUID using gen_random_uuid()
-- See docs/architecture/db-schema-decisions.md

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS documents;
CREATE SCHEMA IF NOT EXISTS land;
CREATE SCHEMA IF NOT EXISTS sales;

CREATE TABLE core.orgs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES core.orgs(id),
    email TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'staff', 'readonly')),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES core.orgs(id),
    contact_type TEXT NOT NULL CHECK (
        contact_type IN ('developer', 'buyer', 'realtor', 'vendor', 'lawyer')
    ),
    full_name TEXT NOT NULL,
    company_name TEXT,
    email TEXT,
    phone TEXT,
    address TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.developments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES core.orgs(id),
    developer_contact_id UUID REFERENCES core.contacts(id),
    name TEXT NOT NULL,
    municipality TEXT,
    province TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.lots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    development_id UUID NOT NULL REFERENCES core.developments(id),
    legal_description_raw TEXT,
    legal_description_normalized TEXT NOT NULL UNIQUE,
    civic_address TEXT,
    street_number TEXT,
    street_name TEXT,
    lot_number TEXT,
    block TEXT,
    plan TEXT,
    status TEXT NOT NULL DEFAULT 'land_contracted' CHECK (
        status IN (
            'land_contracted',
            'land_purchased',
            'serviced',
            'sale_signed',
            'build_active',
            'possession',
            'warranty'
        )
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.reminders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lot_id UUID REFERENCES core.lots(id),
    entity_table TEXT NOT NULL,
    entity_id UUID NOT NULL,
    reminder_type TEXT NOT NULL,
    due_at TIMESTAMPTZ NOT NULL,
    is_sent BOOLEAN NOT NULL DEFAULT false,
    is_dismissed BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.audit_log (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES core.users(id),
    schema_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    record_id UUID NOT NULL,
    action TEXT NOT NULL CHECK (
        action IN ('INSERT', 'UPDATE', 'DELETE', 'PROMOTE', 'MATCHED_EXISTING')
    ),
    old_data JSONB,
    new_data JSONB,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE documents.documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES core.orgs(id),
    doc_type TEXT NOT NULL CHECK (
        doc_type IN ('land_otp', 'sale_otp', 'invoice', 'legal', 'other')
    ),
    status TEXT NOT NULL DEFAULT 'received' CHECK (
        status IN (
            'received',
            'classifying',
            'extracting',
            'in_review',
            'approved',
            'rejected'
        )
    ),
    original_filename TEXT,
    minio_bucket TEXT NOT NULL DEFAULT 'documents',
    minio_key TEXT NOT NULL,
    file_size_bytes BIGINT,
    checksum_sha256 TEXT UNIQUE,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    received_from_email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE documents.ingestions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents.documents(id),
    ocr_method TEXT NOT NULL CHECK (
        ocr_method IN ('pdfplumber', 'tesseract', 'manual')
    ),
    ocr_text TEXT,
    ocr_confidence NUMERIC(4,3),
    page_count INTEGER,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE TABLE documents.extractions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingestion_id UUID NOT NULL REFERENCES documents.ingestions(id),
    model_provider TEXT NOT NULL,
    model_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    extracted_payload JSONB NOT NULL,
    field_confidences JSONB DEFAULT '{}'::jsonb,
    low_confidence_fields TEXT[] DEFAULT '{}'::TEXT[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE documents.reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    extraction_id UUID NOT NULL REFERENCES documents.extractions(id),
    reviewed_by UUID REFERENCES core.users(id),
    reviewed_payload JSONB NOT NULL,
    edited_fields TEXT[] DEFAULT '{}'::TEXT[],
    decision TEXT CHECK (decision IN ('approved', 'rejected', 'deferred')),
    rejection_reason TEXT,
    reviewed_at TIMESTAMPTZ,
    promoted_at TIMESTAMPTZ
);

CREATE TABLE land.agreements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents.documents(id),
    review_id UUID NOT NULL REFERENCES documents.reviews(id),
    developer_contact_id UUID NOT NULL REFERENCES core.contacts(id),
    development_id UUID NOT NULL REFERENCES core.developments(id),
    agreement_date DATE NOT NULL,
    interest_rate NUMERIC(6,4),
    interest_type TEXT CHECK (interest_type IN ('flat', 'prime_plus_fixed')),
    interest_terms TEXT,
    interest_free_from DATE,
    balance_due_rule TEXT,
    total_purchase_price NUMERIC(15,2) NOT NULL,
    municipality TEXT,
    notable_clauses JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE land.security_deposit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agreement_id UUID NOT NULL UNIQUE REFERENCES land.agreements(id),
    rate_per_lot NUMERIC(15,2) NOT NULL,
    maximum_amount NUMERIC(15,2) NOT NULL,
    calculated_amount NUMERIC(15,2) NOT NULL,
    due_trigger TEXT NOT NULL DEFAULT 'on_signing',
    paid_at TIMESTAMPTZ,
    paid_amount NUMERIC(15,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE land.lot_terms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lot_id UUID NOT NULL REFERENCES core.lots(id),
    agreement_id UUID NOT NULL REFERENCES land.agreements(id),
    purchase_price NUMERIC(15,2) NOT NULL,
    frontage_metres NUMERIC(8,2),
    frontage_feet NUMERIC(8,2),
    lot_notes TEXT,
    balance_due_date DATE,
    possession_date DATE,
    lot_specific_conditions TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (lot_id, agreement_id)
);

CREATE TABLE land.deposit_schedule (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lot_terms_id UUID NOT NULL REFERENCES land.lot_terms(id),
    lot_id UUID NOT NULL REFERENCES core.lots(id),
    deposit_number INTEGER NOT NULL,
    amount NUMERIC(15,2) NOT NULL,
    due_date DATE,
    trigger_type TEXT NOT NULL CHECK (
        trigger_type IN ('on_signing', 'fixed_date', 'milestone')
    ),
    trigger_description TEXT,
    notes TEXT,
    paid_at TIMESTAMPTZ,
    paid_amount NUMERIC(15,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE land.milestones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agreement_id UUID NOT NULL REFERENCES land.agreements(id),
    lot_id UUID REFERENCES core.lots(id),
    milestone_name TEXT NOT NULL,
    description TEXT,
    expected_date DATE,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sales.agreements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lot_id UUID NOT NULL REFERENCES core.lots(id),
    document_id UUID NOT NULL REFERENCES documents.documents(id),
    review_id UUID NOT NULL REFERENCES documents.reviews(id),
    sale_price NUMERIC(15,2) NOT NULL,
    agreement_date DATE,
    possession_date DATE,
    condition_removal_date DATE,
    status TEXT NOT NULL DEFAULT 'received' CHECK (
        status IN (
            'received',
            'conditions_pending',
            'firm',
            'build_started',
            'possession_complete',
            'collapsed'
        )
    ),
    conditions JSONB DEFAULT '[]'::jsonb,
    notable_clauses JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sales.parties (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agreement_id UUID NOT NULL REFERENCES sales.agreements(id),
    contact_id UUID NOT NULL REFERENCES core.contacts(id),
    party_role TEXT NOT NULL CHECK (
        party_role IN ('buyer', 'co_buyer', 'buyers_realtor', 'sellers_realtor')
    ),
    is_primary BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sales.deposit_schedule (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agreement_id UUID NOT NULL REFERENCES sales.agreements(id),
    deposit_number INTEGER NOT NULL,
    amount NUMERIC(15,2) NOT NULL,
    due_date DATE,
    held_by TEXT CHECK (held_by IN ('realtor', 'lawyer', 'builder')),
    paid_at TIMESTAMPTZ,
    paid_amount NUMERIC(15,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_core_lots_development_status
    ON core.lots (development_id, status);

CREATE INDEX idx_core_reminders_lot_due_sent
    ON core.reminders (lot_id, due_at, is_sent);

CREATE INDEX idx_core_audit_log_table_record_changed_at
    ON core.audit_log (table_name, record_id, changed_at DESC);

-- Unique constraints on documents.documents(checksum_sha256) and
-- core.lots(legal_description_normalized) provide the requested indexes
-- for those identity keys.
CREATE INDEX idx_documents_documents_status_doc_type
    ON documents.documents (status, doc_type);

CREATE INDEX idx_documents_ingestions_document_id
    ON documents.ingestions (document_id);

CREATE INDEX idx_documents_extractions_ingestion_id
    ON documents.extractions (ingestion_id);

CREATE INDEX idx_documents_reviews_extraction_decision
    ON documents.reviews (extraction_id, decision);

CREATE INDEX idx_land_agreements_development_document
    ON land.agreements (development_id, document_id);

-- The UNIQUE (lot_id, agreement_id) constraint on land.lot_terms provides
-- the requested composite lookup index.
CREATE INDEX idx_land_deposit_schedule_lot_due_paid
    ON land.deposit_schedule (lot_id, due_date, paid_at);

CREATE INDEX idx_sales_agreements_lot_status
    ON sales.agreements (lot_id, status);
