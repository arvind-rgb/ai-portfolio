-- ShipHop.AI schema. Deliberately isolated in its own booker_* tables: the same
-- database also hosts a consumer order table whose status changes fire a
-- notification worker (emails, WhatsApp, push, reconciliation). None of that may
-- fire for third-party businesses' parcels, so these tables have NO NOTIFY trigger.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Tenant = the business using ShipHop.AI.
CREATE TABLE IF NOT EXISTS booker_tenant (
    tenant_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name       VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    status     VARCHAR(16) DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS booker_user (
    user_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID NOT NULL REFERENCES booker_tenant(tenant_id),
    email      VARCHAR(255) UNIQUE NOT NULL,
    role       VARCHAR(16) DEFAULT 'operator',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Operator login credentials (created by the admin module). One login per tenant.
-- password_hash is scrypt (see server/src/pwd.js) — never plaintext.
CREATE TABLE IF NOT EXISTS booker_operator_auth (
    tenant_id     UUID NOT NULL REFERENCES booker_tenant(tenant_id),
    login         VARCHAR(64) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (tenant_id)
);

-- ONE session table for ALL couriers (one row per tenant x courier).
-- Per-tenant (a business's team shares one connection per provider).
-- `credentials` is an ENCRYPTED envelope (see server/src/crypto.js) — never plaintext.
CREATE TABLE IF NOT EXISTS booker_provider_session (
    tenant_id     UUID NOT NULL REFERENCES booker_tenant(tenant_id),
    provider      VARCHAR(16) NOT NULL,   -- porter_web|shadowfax|shiprocket|rapido|uber|delhivery
    credentials   TEXT,                   -- encrypted JSON envelope; NULL = disconnected
    metadata      JSONB,                  -- city, uuids, couriers, options cache, home lat/lng
    account_label VARCHAR(255),           -- the 3PL mobile / business name, for the UI
    created_at    TIMESTAMP DEFAULT NOW(),
    refreshed_at  TIMESTAMP DEFAULT NOW(),
    last_used_at  TIMESTAMP,
    last_401_at   TIMESTAMP,
    PRIMARY KEY (tenant_id, provider)
);

-- Friendly, monotonic booking references (SH-1000, SH-1001, …) — readable in ops
-- and cancel commands, and it lets the pre-Postgres file-store ids (BB-####)
-- import cleanly (the column is TEXT, not UUID).
CREATE SEQUENCE IF NOT EXISTS booker_booking_ref_seq START 1000;

-- One booking. Provider-agnostic core + a provider blob.
CREATE TABLE IF NOT EXISTS booker_booking (
    booking_id           TEXT PRIMARY KEY DEFAULT ('SH-' || nextval('booker_booking_ref_seq')),
    tenant_id            UUID NOT NULL REFERENCES booker_tenant(tenant_id),
    booked_by            UUID REFERENCES booker_user(user_id),
    provider             VARCHAR(16) NOT NULL,
    provider_order_id    VARCHAR(64),
    provider_ids         JSONB,           -- some couriers need several upstream ids per order

    status               VARCHAR(32),     -- unified vocabulary: Booked|Rider assigned|Picked up|In transit|Delivered|Cancelled|Failed
    status_code          VARCHAR(8),
    status_raw           TEXT,            -- upstream's own string — keep it

    pickup               JSONB NOT NULL,  -- {name,phone,address,lat,lng,city,state,pincode,email}
    "drop"               JSONB NOT NULL,

    estimated_fare       NUMERIC(10,2),
    actual_fare          NUMERIC(10,2),
    rider_name           VARCHAR(128),
    rider_number         VARCHAR(20),     -- may be a MASKED bridge number
    rider_vehicle_number VARCHAR(64),
    rider_lat            DOUBLE PRECISION,
    rider_lng            DOUBLE PRECISION,
    pickup_otp           VARCHAR(8),
    drop_otp             VARCHAR(8),
    tracking_url         TEXT,

    order_number         VARCHAR(64),     -- the tenant's own reference (optional)
    instructions         TEXT,            -- rider note ("gate code", "call on arrival")

    request_payload      JSONB,
    response_payload     JSONB,
    logs                 JSONB,

    created_at           TIMESTAMP DEFAULT NOW(),
    delivered_at         TIMESTAMP,       -- stamped when status first reaches Delivered (for reporting)
    last_polled_at       TIMESTAMP,
    rebooked_from        TEXT REFERENCES booker_booking(booking_id)
);

-- Back-fill for databases migrated before these columns existed.
ALTER TABLE booker_booking ADD COLUMN IF NOT EXISTS order_number VARCHAR(64);
ALTER TABLE booker_booking ADD COLUMN IF NOT EXISTS instructions TEXT;
ALTER TABLE booker_booking ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_booker_booking_active
    ON booker_booking (last_polled_at NULLS FIRST)
    WHERE status NOT IN ('Delivered','Cancelled','Failed');
CREATE INDEX IF NOT EXISTS idx_booker_booking_provider_order
    ON booker_booking (provider, provider_order_id);
CREATE INDEX IF NOT EXISTS idx_booker_booking_tenant
    ON booker_booking (tenant_id, created_at DESC);

-- Multi-provider estimate results (cache + audit for the compare screen).
CREATE TABLE IF NOT EXISTS booker_estimate (
    estimate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES booker_tenant(tenant_id),
    pickup      JSONB NOT NULL,
    "drop"      JSONB NOT NULL,
    results     JSONB NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    expires_at  TIMESTAMP
);

-- Seed the fixed dev tenant used when BOOKER_JWT_SECRET is unset (see server/src/auth.js).
INSERT INTO booker_tenant (tenant_id, name)
VALUES ('00000000-0000-0000-0000-000000000001', 'Dev Tenant')
ON CONFLICT (tenant_id) DO NOTHING;
