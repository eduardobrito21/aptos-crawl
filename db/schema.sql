-- Aptos SP — canonical SQLite schema.
-- Source of truth (ADR-003). Docs describe; this file defines.
-- Apply with: sqlite3 aptos.db < db/schema.sql

-- Main listings table.
CREATE TABLE IF NOT EXISTS aptos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,                   -- 'zap' | 'quintoandar'
    source_id TEXT NOT NULL,                -- native listing ID
    -- Canonical listing URL. NOT UNIQUE: ZAP republishes the same
    -- listing under different slugs across snapshots, and the same URL
    -- can legitimately appear with different (source, source_id) pairs.
    -- Identity is `(source, source_id)`, not URL.
    url TEXT NOT NULL,
    bairro TEXT,
    endereco TEXT,
    endereco_normalized TEXT,               -- ADR-006 (cross-platform dedup)
    area_m2 REAL,
    quartos INTEGER,
    suites INTEGER,
    banheiros INTEGER,
    vagas INTEGER,
    andar TEXT,
    mobiliado BOOLEAN,
    -- Qualitative criteria, ADR-007. Tri-state via NULL.
    chuveiro_gas BOOLEAN,
    chuveirinho BOOLEAN,
    ar_condicionado BOOLEAN,
    vidro_anti_ruido BOOLEAN,
    cozinha_layout TEXT,                    -- 'isolada' | 'americana' | 'integrada' | NULL
    lavabo BOOLEAN,
    internet_fibra TEXT,
    -- Source text for qualitative extraction (ADR-007). Filled at scrape
    -- time and re-read by `pipeline/extract.py`; storing it lets enrich
    -- re-run without re-scraping when keywords.yaml changes.
    descricao TEXT,
    amenities TEXT,                         -- JSON array of source amenity codes
    extracted_at_hash TEXT,                 -- value of raw_html_hash at last extract
    -- Detail-page enrichment, populated by `cli/details.py`. The
    -- listings API gives us description/amenities for free; the detail
    -- page adds these fields the API doesn't return.
    anunciante_code TEXT,                   -- broker's internal listing id
    criado_em DATE,                         -- "Anúncio criado em..." date
    detail_fetched_at DATETIME,             -- idempotency key for detail fetch
    -- QA detail-page extras (Plan 0009 part 2). ZAP exposes some of
    -- these on the listings API so its detail parser doesn't repeat
    -- them; for QA the detail page is the only public surface.
    accepts_pets BOOLEAN,
    near_subway BOOLEAN,
    tenant_service_fee REAL,
    home_protection_fee REAL,
    construction_year INTEGER,
    -- Commute enrichment, ADR-010. NULL until pipeline runs.
    address_lat REAL,
    address_lng REAL,
    address_source TEXT,                    -- 'structured' | 'regex' | 'llm' | 'geocoded_only'
    address_precision TEXT,                 -- 'rooftop' | 'street' | 'neighborhood'
    commute_km REAL,
    commute_min INTEGER,
    commute_climb_m INTEGER,                -- nullable; only if Elevation API ran
    commute_quality TEXT,                   -- 'excellent' | 'good' | 'acceptable' | 'bad'
    commute_route_source TEXT,              -- 'bicycle' | 'walk_estimate' (ADR-010 fallback)
    commute_computed_at DATETIME,
    -- Metadata
    scraped_at DATETIME NOT NULL,
    last_seen DATETIME NOT NULL,
    raw_html_hash TEXT,                     -- changed? re-extract
    eligible BOOLEAN,                       -- passes filters.yaml
    possible_dup_of INTEGER REFERENCES aptos(id),
    -- LLM enrichment audit, ADR-009. 'keyword' | 'llm' | mixed.
    extracted_by TEXT,
    UNIQUE(source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_aptos_eligible ON aptos(eligible);
CREATE INDEX IF NOT EXISTS idx_aptos_bairro ON aptos(bairro);
CREATE INDEX IF NOT EXISTS idx_aptos_source ON aptos(source);

-- Daily snapshot price history, ADR-004.
CREATE TABLE IF NOT EXISTS precos_historico (
    apto_id INTEGER NOT NULL REFERENCES aptos(id),
    snapshot_date DATE NOT NULL,
    aluguel REAL,
    condominio REAL,
    iptu REAL,
    total REAL,
    is_change BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (apto_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS fotos (
    apto_id INTEGER NOT NULL REFERENCES aptos(id),
    url TEXT NOT NULL,
    position INTEGER,
    PRIMARY KEY (apto_id, url)
);

-- Manual fields edited in Notion, preserved across exports (ADR-008).
CREATE TABLE IF NOT EXISTS manual_overrides (
    apto_id INTEGER PRIMARY KEY REFERENCES aptos(id),
    status TEXT,
    score INTEGER,
    notas TEXT,
    updated_at DATETIME
);

-- Per-run audit log. Used for auto-disable (ADR-005) and cost tracking.
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,                   -- 'zap' | 'quintoandar' | 'enrich' | 'commute' | 'export'
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    status TEXT,                            -- 'success' | 'failed' | 'partial' | 'disabled'
    n_listings INTEGER,
    n_new INTEGER,
    n_updated INTEGER,
    n_errors INTEGER,
    error_summary TEXT,
    maps_cost_usd REAL,
    llm_cost_usd REAL
);

-- Views

CREATE VIEW IF NOT EXISTS v_notion_export AS
SELECT
    a.*,
    p.aluguel,
    p.condominio,
    p.iptu,
    p.total,
    m.status AS manual_status,
    m.score AS manual_score,
    m.notas AS manual_notas
FROM aptos a
LEFT JOIN precos_historico p
    ON p.apto_id = a.id
    AND p.snapshot_date = (
        SELECT MAX(snapshot_date)
        FROM precos_historico
        WHERE apto_id = a.id
    )
LEFT JOIN manual_overrides m ON m.apto_id = a.id
WHERE a.eligible = 1;

CREATE VIEW IF NOT EXISTS v_precos_changes AS
SELECT apto_id, snapshot_date, aluguel, total
FROM precos_historico
WHERE is_change = 1
ORDER BY snapshot_date DESC;

CREATE VIEW IF NOT EXISTS v_possible_dups AS
SELECT
    a.id, a.source, a.source_id, a.endereco, a.area_m2, a.quartos,
    d.id AS dup_of_id, d.source AS dup_of_source, d.endereco AS dup_of_endereco
FROM aptos a
JOIN aptos d ON a.possible_dup_of = d.id
ORDER BY a.id;
