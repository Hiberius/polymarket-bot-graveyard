CREATE TABLE IF NOT EXISTS markets (
    id SERIAL PRIMARY KEY,
    polymarket_id TEXT UNIQUE NOT NULL,
    question TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'unknown',
    resolution_time TIMESTAMPTZ NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_price NUMERIC(5,4),
    volume_24h NUMERIC,
    book_depth NUMERIC,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analyses (
    id SERIAL PRIMARY KEY,
    market_id INT NOT NULL REFERENCES markets(id),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model_estimates JSONB NOT NULL,
    ensemble_probability NUMERIC(5,4) NOT NULL,
    ensemble_stdev NUMERIC(5,4) NOT NULL,
    quant_signals JSONB NOT NULL,
    edge NUMERIC(5,4) NOT NULL,
    web_research_summary TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    market_id INT NOT NULL REFERENCES markets(id),
    analysis_id INT NOT NULL REFERENCES analyses(id),
    side TEXT NOT NULL CHECK (side IN ('YES', 'NO')),
    entry_price NUMERIC(5,4) NOT NULL,
    position_size_usd NUMERIC NOT NULL,
    shares NUMERIC NOT NULL,
    kelly_inputs JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'filled', 'partial', 'cancelled', 'closed')),
    exit_price NUMERIC(5,4),
    exit_reason TEXT CHECK (exit_reason IN ('resolution', 'early_exit', 'stop_loss')),
    pnl NUMERIC,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS model_performance (
    id SERIAL PRIMARY KEY,
    model_name TEXT UNIQUE NOT NULL,
    resolved_count INT NOT NULL DEFAULT 0,
    brier_score_ema NUMERIC(6,4) NOT NULL DEFAULT 0.25,
    trust_weight NUMERIC(4,3) NOT NULL DEFAULT 0.333,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS system_state (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    bankroll NUMERIC NOT NULL,
    total_deployed NUMERIC NOT NULL DEFAULT 0,
    daily_pnl NUMERIC NOT NULL DEFAULT 0,
    kelly_mult NUMERIC(4,3) NOT NULL DEFAULT 0.250,
    edge_threshold NUMERIC(4,3) NOT NULL DEFAULT 0.050,
    category_scores JSONB NOT NULL DEFAULT '{}',
    calibration_corrections JSONB NOT NULL DEFAULT '{}',
    last_scan_at TIMESTAMPTZ,
    circuit_breaker_until TIMESTAMPTZ
);

-- Initialize model performance rows
INSERT INTO model_performance (model_name, trust_weight) VALUES
    ('claude-opus-4-6', 0.333),
    ('gpt-5.4-mini', 0.333),
    ('gemini-2.5-flash', 0.333)
ON CONFLICT (model_name) DO NOTHING;

-- v2: Strategy column on trades
ALTER TABLE trades ADD COLUMN IF NOT EXISTS strategy TEXT NOT NULL DEFAULT 'forecast';

-- v2.5: Expand strategy CHECK for all strategies
ALTER TABLE trades DROP CONSTRAINT IF EXISTS trades_strategy_check;
ALTER TABLE trades ADD CONSTRAINT trades_strategy_check
    CHECK (strategy IN ('arbitrage', 'snipe', 'forecast', 'market_maker', 'mean_reversion', 'cross_venue', 'political', 'news_catalyst', 'live_game', 'weather', 'phantom', 'whale'))
    NOT VALID;

-- v2: Strategy performance tracking
CREATE TABLE IF NOT EXISTS strategy_performance (
    id SERIAL PRIMARY KEY,
    strategy TEXT UNIQUE NOT NULL,
    total_trades INT NOT NULL DEFAULT 0,
    winning_trades INT NOT NULL DEFAULT 0,
    total_pnl NUMERIC NOT NULL DEFAULT 0,
    avg_edge NUMERIC(5,4) NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO strategy_performance (strategy) VALUES
    ('arbitrage'), ('snipe'), ('forecast')
ON CONFLICT (strategy) DO NOTHING;

INSERT INTO strategy_performance (strategy) VALUES ('live_game') ON CONFLICT DO NOTHING;

-- v2: Market relationships for arbitrage detection
CREATE TABLE IF NOT EXISTS market_relationships (
    id SERIAL PRIMARY KEY,
    group_id TEXT NOT NULL,
    market_id INT NOT NULL REFERENCES markets(id),
    relationship_type TEXT NOT NULL
        CHECK (relationship_type IN ('exhaustive_group', 'temporal_subset', 'complement')),
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(group_id, market_id)
);

-- v2: Post-breaker cooldown tracking
ALTER TABLE system_state ADD COLUMN IF NOT EXISTS post_breaker_until TIMESTAMPTZ;

-- v3: Circuit breaker reason (for dashboard banner)
ALTER TABLE system_state ADD COLUMN IF NOT EXISTS circuit_breaker_reason TEXT;

-- v2.1: CLOB order tracking
ALTER TABLE trades ADD COLUMN IF NOT EXISTS clob_order_id TEXT;

-- v2.1: Expand trade status for dry-run and fill tracking
ALTER TABLE trades DROP CONSTRAINT IF EXISTS trades_status_check;
ALTER TABLE trades ADD CONSTRAINT trades_status_check
    CHECK (status IN ('open', 'filled', 'partial', 'cancelled', 'closed',
                      'dry_run', 'dry_run_resolved', 'archived', 'stuck'))
    NOT VALID;

-- v2.3: Expand exit_reason for time-stop and arb TTL exits
ALTER TABLE trades DROP CONSTRAINT IF EXISTS trades_exit_reason_check;
ALTER TABLE trades ADD CONSTRAINT trades_exit_reason_check
    CHECK (exit_reason IN ('resolution', 'early_exit', 'stop_loss', 'take_profit', 'time_stop', 'arb_ttl_expired'))
    NOT VALID;

-- v2.4: Learning system — per-strategy learned parameters
ALTER TABLE strategy_performance ADD COLUMN IF NOT EXISTS learned_params JSONB NOT NULL DEFAULT '{}';

-- v2.6: Dry-run friction model — make paper numbers match live conditions
--
-- The dry_run path historically stored entries at Gamma mid-price with zero
-- fees, zero slippage, instant resolution. That baked illusory edge into
-- every strategy. These columns let us keep the naive values (entry_price,
-- pnl) for backward compatibility AND store the adjusted values alongside.
-- See polybot/trading/friction.py for the math and doc links.
ALTER TABLE trades ADD COLUMN IF NOT EXISTS adjusted_entry_price NUMERIC(5,4);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS simulated_slippage_cents REAL;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS simulated_fill_delay_ms INTEGER;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_fee_usd NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_fee_usd NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS adjusted_pnl NUMERIC;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS fill_status TEXT NOT NULL DEFAULT 'filled';
ALTER TABLE trades ADD COLUMN IF NOT EXISTS applied_adverse_selection_bps INTEGER DEFAULT 0;

-- Constrain fill_status values
ALTER TABLE trades DROP CONSTRAINT IF EXISTS trades_fill_status_check;
ALTER TABLE trades ADD CONSTRAINT trades_fill_status_check
    CHECK (fill_status IN ('filled', 'partial', 'rejected', 'expired', 'unknown'))
    NOT VALID;

-- Expand trade status for pre-resolution waiting and friction rejection
-- v3.9: 'pending_submit' added for orphan-safe order lifecycle (H2)
ALTER TABLE trades DROP CONSTRAINT IF EXISTS trades_status_check;
ALTER TABLE trades ADD CONSTRAINT trades_status_check
    CHECK (status IN ('pending_submit', 'open', 'filled', 'partial',
                      'cancelled', 'closed',
                      'dry_run', 'dry_run_resolved', 'dry_run_unfilled',
                      'dry_run_pending_resolution',
                      'archived', 'stuck'))
    NOT VALID;

-- Index for realism-summary dashboard queries
CREATE INDEX IF NOT EXISTS idx_trades_fill_status ON trades(fill_status);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_markets_resolution ON markets(resolution_time);
CREATE INDEX IF NOT EXISTS idx_markets_polymarket_id ON markets(polymarket_id);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_market_id ON trades(market_id);
CREATE INDEX IF NOT EXISTS idx_analyses_market_id ON analyses(market_id);
CREATE INDEX IF NOT EXISTS idx_analyses_timestamp ON analyses(timestamp);
CREATE INDEX IF NOT EXISTS idx_market_relationships_group ON market_relationships(group_id);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);
CREATE INDEX IF NOT EXISTS idx_trades_closed_at ON trades(closed_at);
CREATE INDEX IF NOT EXISTS idx_trades_clob_order_id ON trades(clob_order_id);

-- v2.5: AI decisions table (whale signals, gate decisions, activity log)
CREATE TABLE IF NOT EXISTS ai_decisions (
    id SERIAL PRIMARY KEY,
    engine TEXT NOT NULL,
    question TEXT,
    estimated_prob NUMERIC(5,4),
    market_prob NUMERIC(5,4),
    divergence_pct NUMERIC(5,4),
    action TEXT NOT NULL,
    reasoning TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ai_decisions_ts ON ai_decisions(timestamp);
CREATE INDEX IF NOT EXISTS idx_ai_decisions_engine ON ai_decisions(engine);

-- v5: Phantom signal audit trail (every 5m window logged)
CREATE TABLE IF NOT EXISTS phantom_signals (
    id SERIAL PRIMARY KEY,
    window_ts INT NOT NULL,
    btc_price NUMERIC NOT NULL DEFAULT 0,
    window_delta_pct NUMERIC(8,5) DEFAULT 0,
    trend_10m_pct NUMERIC(8,5) DEFAULT 0,
    ewma_vol NUMERIC(8,6) DEFAULT 0,
    cvd NUMERIC DEFAULT 0,
    ob_imbalance NUMERIC(6,4) DEFAULT 0,
    composite_score NUMERIC(6,4) DEFAULT 0,
    fair_prob_up NUMERIC(6,4) DEFAULT 0,
    dislocation NUMERIC(6,4) DEFAULT 0,
    ev_post_fee NUMERIC(6,4) DEFAULT 0,
    side TEXT DEFAULT '',
    should_trade BOOLEAN NOT NULL DEFAULT FALSE,
    abstention_reason TEXT DEFAULT '',
    trade_id INT REFERENCES trades(id),
    fee_estimate_usd NUMERIC(10,4) DEFAULT 0,
    slippage_estimate_cents NUMERIC(6,2) DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_phantom_signals_window ON phantom_signals(window_ts);
ALTER TABLE phantom_signals ADD COLUMN IF NOT EXISTS fee_estimate_usd NUMERIC(10,4) DEFAULT 0;
ALTER TABLE phantom_signals ADD COLUMN IF NOT EXISTS slippage_estimate_cents NUMERIC(6,2) DEFAULT 0;

-- v5: Chainlink oracle prices (canonical DDL — replaces runtime CREATE in __main__)
CREATE TABLE IF NOT EXISTS chainlink_prices (
    id SERIAL PRIMARY KEY,
    price NUMERIC NOT NULL,
    ts NUMERIC NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chainlink_prices_ts ON chainlink_prices(ts DESC);

-- v5.1: Dashboard hot-path indexes
CREATE INDEX IF NOT EXISTS idx_trades_opened_at ON trades(opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_decisions_action_ts ON ai_decisions(action, timestamp DESC);

-- v5.1: Deduplicate phantom signals, then enforce uniqueness per window
DELETE FROM phantom_signals a USING phantom_signals b
    WHERE a.id < b.id AND a.window_ts = b.window_ts;
DO $$ BEGIN
    ALTER TABLE phantom_signals ADD CONSTRAINT phantom_signals_window_ts_key UNIQUE (window_ts);
EXCEPTION
    WHEN duplicate_object THEN NULL;   -- constraint already exists
    WHEN duplicate_table THEN NULL;    -- underlying unique index already exists from prior run
END $$;

-- v2.5: Ensure all strategies have performance rows
INSERT INTO strategy_performance (strategy) VALUES
    ('arbitrage'), ('snipe'), ('forecast'), ('live_game'),
    ('weather'), ('phantom'), ('news_catalyst'), ('whale'),
    ('political'), ('mean_reversion'), ('cross_venue'), ('market_maker')
ON CONFLICT (strategy) DO NOTHING;

-- v3.8 (Phase C3): trades_rejected — persist every rejection from
-- friction.simulate_fill() and the risk manager. Today these events
-- only appear in the log stream and are dropped from dashboard counts.
CREATE TABLE IF NOT EXISTS trades_rejected (
    id SERIAL PRIMARY KEY,
    market_id INT REFERENCES markets(id),
    strategy TEXT NOT NULL,
    side TEXT,
    price NUMERIC(5,4),
    size_usd NUMERIC,
    shares NUMERIC,
    rejection_reason TEXT NOT NULL,
    rejection_details JSONB DEFAULT '{}'::jsonb,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trades_rejected_strategy ON trades_rejected(strategy);
CREATE INDEX IF NOT EXISTS idx_trades_rejected_ts ON trades_rejected(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_trades_rejected_reason ON trades_rejected(rejection_reason);

-- v3.8 (Phase C3): phantom_ai_votes — one row per model per consensus
-- round (Opus + GPT + Gemini × approve/reject). Previously the three
-- individual votes were collapsed into a single ai_decisions row, so
-- the AI GATE tab could not show per-model trust drift.
CREATE TABLE IF NOT EXISTS phantom_ai_votes (
    id SERIAL PRIMARY KEY,
    market_id INT REFERENCES markets(id),
    question TEXT,
    market_price NUMERIC(5,4),
    proposed_side TEXT,
    model TEXT NOT NULL,
    approved BOOLEAN NOT NULL,
    reasoning TEXT,
    consensus_outcome TEXT,  -- 'APPROVE' | 'REJECT'
    votes_for INT,
    votes_total INT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_phantom_ai_votes_market ON phantom_ai_votes(market_id);
CREATE INDEX IF NOT EXISTS idx_phantom_ai_votes_ts ON phantom_ai_votes(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_phantom_ai_votes_consensus ON phantom_ai_votes(consensus_outcome);
CREATE INDEX IF NOT EXISTS idx_phantom_ai_votes_model ON phantom_ai_votes(model);

-- v3.9 (Pre-Live Hardening H1+H2+H3): idempotent order tracking + orphan reconcile
-- nonce is the EIP-712 deterministic identifier we pass to py-clob-client OrderArgs.
-- Derived from trades.id so a retry of the same logical order collides on CLOB.
ALTER TABLE trades ADD COLUMN IF NOT EXISTS nonce BIGINT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_nonce ON trades(nonce) WHERE nonce IS NOT NULL;

-- orphan_orders: drift between DB and CLOB detected at startup reconcile.
-- source = 'clob_only' (CLOB has it, DB does not) | 'db_only' (DB has it, CLOB does not).
-- Reviewed manually; resolution_note explains how capital was released or order cancelled.
CREATE TABLE IF NOT EXISTS orphan_orders (
    id SERIAL PRIMARY KEY,
    clob_order_id TEXT NOT NULL,
    source TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    resolution_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_orphan_orders_unresolved ON orphan_orders(detected_at) WHERE resolved_at IS NULL;

-- v4.0 (Chainlink Lag Edge — Phase 0): phantom_book_observation
-- Passive observer of Polymarket BTC 5-min binary book + Chainlink price.
-- One row per (window, secs_left, scan). Used to derive whether the order
-- book has repriced relative to the Chainlink truth at T-30s/T-10s.
-- ZERO trades are generated from this table; it is observation-only.
CREATE TABLE IF NOT EXISTS phantom_book_observation (
    id SERIAL PRIMARY KEY,
    window_ts INT NOT NULL,                  -- unix ts of window END (5-min boundary)
    secs_left INT NOT NULL,                  -- seconds remaining when observed
    chainlink_price NUMERIC(14,2) NOT NULL,  -- chainlink BTC at observation time
    chainlink_window_open NUMERIC(14,2),     -- chainlink BTC at window_ts - 300
    signal_bps NUMERIC(10,3),                -- (chainlink_now - chainlink_open)/open * 10000, signed
    sig_direction TEXT,                      -- 'UP' | 'DOWN' | 'FLAT'
    best_ask_yes NUMERIC(6,4),               -- Polymarket best ask, YES outcome (UP)
    best_ask_no NUMERIC(6,4),                -- Polymarket best ask, NO outcome (DOWN)
    best_bid_yes NUMERIC(6,4),
    best_bid_no NUMERIC(6,4),
    book_fetch_ms INT,                       -- latency to fetch both books (ms)
    chainlink_age_s NUMERIC(6,2),            -- staleness of chainlink reading (s)
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pbo_window_secs ON phantom_book_observation(window_ts, secs_left);
CREATE INDEX IF NOT EXISTS idx_pbo_observed ON phantom_book_observation(observed_at DESC);

-- v5.0 (Mispricing Detector — Phase 2): mispricing_signals
-- Audit trail for every mispricing event detected by MispricingDetector.
-- One row per candidate signal, regardless of tier or outcome.
-- Updated in-place as the signal progresses through AI gate and order placement.
CREATE TABLE IF NOT EXISTS mispricing_signals (
    id              SERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    market_id       TEXT NOT NULL,           -- Polymarket conditionId / slug
    token_id        TEXT NOT NULL,           -- outcome token ID traded (YES or NO)
    side            TEXT NOT NULL,           -- 'YES' (UP) | 'NO' (DOWN)
    signal_bps      DOUBLE PRECISION NOT NULL,  -- chainlink momentum at detection time
    secs_left       INT NOT NULL,            -- seconds until window close
    fair_prob       DOUBLE PRECISION NOT NULL,  -- empirical P(side wins) from fair_price.py
    book_implied    DOUBLE PRECISION NOT NULL,  -- Polymarket best ask for this side
    mispricing_pp   DOUBLE PRECISION NOT NULL,  -- (fair_prob - book_implied) * 100
    obs_bucket      INT NOT NULL,            -- T+seconds_into_window bucket used
    bps_bucket      TEXT NOT NULL,           -- magnitude bucket used ('<1','1-3',...)
    tier            INT NOT NULL,            -- 0|1|2 or -1(below threshold)
    ai_approved     BOOLEAN,                 -- NULL=no AI called; True/False=AI vote
    ai_reasoning    TEXT,                    -- reasoning from AI gate
    trade_id        INT REFERENCES trades(id),  -- FK to trades if order placed
    decision        TEXT NOT NULL CHECK (decision IN (
                        'pending','trade','skip_tier',
                        'ai_rejected','ai_timeout'))
);
CREATE INDEX IF NOT EXISTS idx_ms_created ON mispricing_signals (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ms_tier_decision ON mispricing_signals (tier, decision);

-- v6.0 (News-conditioned 15-min BTC trading): news_events + news_trades
-- Source-of-truth for all news ingestion + AI classification + trade audit.
-- Designed for SPECTRIX 3.3 strategy: news-driven, NOT price prediction.
CREATE TABLE IF NOT EXISTS news_events (
    id              SERIAL PRIMARY KEY,
    fetched_at      TIMESTAMPTZ DEFAULT NOW(),
    source          TEXT NOT NULL,                -- 'cryptopanic'|'coindesk'|'forexfactory'
    external_id     TEXT NOT NULL,                -- source-specific id for dedup
    published_at    TIMESTAMPTZ,                  -- as reported by the source
    title           TEXT NOT NULL,
    url             TEXT,
    body_excerpt    TEXT,                         -- first 500 chars
    raw_json        JSONB,
    relevance       TEXT CHECK (relevance IN ('btc_direct','btc_indirect','eth_direct','macro','irrelevant')),
    direction       TEXT CHECK (direction IN ('UP','DOWN','NEUTRAL')),
    magnitude       TEXT CHECK (magnitude IN ('small','medium','large')),
    ai_confidence   DOUBLE PRECISION,             -- 0.0-1.0 consensus strength
    ai_reasoning    TEXT,
    classified_at   TIMESTAMPTZ,
    classifier_latency_ms INT,
    UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_news_fetched ON news_events (fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_relevance ON news_events (relevance, direction);

CREATE TABLE IF NOT EXISTS news_trades (
    id              SERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    news_event_id   INT REFERENCES news_events(id) NOT NULL,
    market_polymarket_id TEXT NOT NULL,
    window_ts       INT NOT NULL,                 -- 15-min window unix ts (resolution time)
    side            TEXT NOT NULL,                -- 'YES' (UP) | 'NO' (DOWN)
    intended_size_usd DOUBLE PRECISION NOT NULL,
    intended_price  DOUBLE PRECISION NOT NULL,
    order_type      TEXT NOT NULL,                -- 'maker'|'taker_fallback'|'skipped'
    trade_id        INT REFERENCES trades(id),    -- FK if order placed
    skip_reason     TEXT,                         -- if order_type='skipped'
    decision_latency_ms INT
);
CREATE INDEX IF NOT EXISTS idx_news_trades_event ON news_trades (news_event_id);

-- v7.0 Long-Tail Sniper (SPECTRIX 3.4): multi-category systematic trading on
-- the 480+ Polymarket long-tail markets HFT bots ignore. Audits the 3-tier
-- funnel (T0 rule filter → T1 Gemini fast → T2 3-AI consensus + disagreement
-- score → trade decision). Audit-first: every signal is persisted regardless
-- of outcome.
CREATE TABLE IF NOT EXISTS lts_signals (
    id              SERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    market_id       TEXT NOT NULL,                  -- Polymarket conditionId
    market_question TEXT NOT NULL,
    category        TEXT NOT NULL,                  -- politics|sports|crypto_alt|pop_culture|tech
    yes_token_id    TEXT NOT NULL,
    no_token_id     TEXT NOT NULL,
    book_yes_ask    DOUBLE PRECISION,               -- best ask side YES at signal time
    book_no_ask     DOUBLE PRECISION,
    market_volume_24h DOUBLE PRECISION,
    resolution_time TIMESTAMPTZ,
    -- Tier 0 (rule-based, always run)
    t0_pass         BOOLEAN NOT NULL,
    t0_reject_reason TEXT,                          -- e.g. 'price_extreme:0.97'
    -- Tier 1 (Gemini fast, only if T0 pass)
    t1_decision     TEXT,                           -- 'pass'|'reject'|'skip'
    t1_estimate     DOUBLE PRECISION,               -- Gemini's fair YES probability
    t1_latency_ms   INT,
    -- Tier 2 (3-AI consensus, only if T1 escalates)
    t2_decision     TEXT,                           -- 'pass'|'reject'|'skip'|'timeout'
    t2_claude_prob  DOUBLE PRECISION,
    t2_gpt_prob     DOUBLE PRECISION,
    t2_gemini_prob  DOUBLE PRECISION,
    t2_avg_prob     DOUBLE PRECISION,
    t2_disagreement DOUBLE PRECISION,               -- max - min across 3 AIs
    t2_latency_ms   INT,
    -- Final trade decision
    final_decision  TEXT NOT NULL CHECK (final_decision IN
                        ('skip','trade_yes','trade_no','no_edge','disagreement_high')),
    edge_pp         DOUBLE PRECISION,               -- (avg_prob - book_implied) * 100
    side            TEXT,                           -- 'YES'|'NO' if trading
    intended_size_usd DOUBLE PRECISION,
    intended_price  DOUBLE PRECISION,
    trade_id        INT REFERENCES trades(id),
    skip_reason     TEXT
);
CREATE INDEX IF NOT EXISTS idx_lts_created ON lts_signals (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lts_market ON lts_signals (market_id);
CREATE INDEX IF NOT EXISTS idx_lts_decision ON lts_signals (final_decision);
CREATE INDEX IF NOT EXISTS idx_lts_category ON lts_signals (category);

-- v7.0 also amends the pre-existing trades.strategy CHECK constraint to admit
-- the three new strategies introduced over the SPECTRIX 3.x series:
--   - mispricing_detector (3.1)
--   - news_conditioned    (3.3)
--   - long_tail_sniper    (3.4)
-- Apply on existing DBs as a one-shot migration:
--   ALTER TABLE trades DROP CONSTRAINT trades_strategy_check;
--   ALTER TABLE trades ADD CONSTRAINT trades_strategy_check CHECK (
--     strategy = ANY (ARRAY[
--       'arbitrage','snipe','forecast','market_maker','mean_reversion',
--       'cross_venue','political','news_catalyst','live_game','weather',
--       'phantom','whale','mispricing_detector','news_conditioned','long_tail_sniper'
--     ])
--   ) NOT VALID;

-- ════════════════════════════════════════════════════════════════════════════
-- v4 maker-only schema (2026-05-04)
-- See docs/SPECTRIX_4_MAKER_DESIGN.md §7
-- All idempotent (CREATE TABLE IF NOT EXISTS, ADD COLUMN IF NOT EXISTS)
-- ════════════════════════════════════════════════════════════════════════════

-- Tier 1: Strategic Selector decisions (3-AI ensemble offline meta-strategy)
CREATE TABLE IF NOT EXISTS strategic_selector_decisions (
  id BIGSERIAL PRIMARY KEY,
  decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  trading_mode TEXT NOT NULL,
  active_markets JSONB NOT NULL DEFAULT '[]'::jsonb,
  size_multiplier REAL NOT NULL DEFAULT 1.0,
  spread_widening_bps INT NOT NULL DEFAULT 0,
  rationale TEXT,
  votes JSONB NOT NULL DEFAULT '{}'::jsonb,
  ensemble_latency_ms INT,
  fallback_used BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_strategic_decided_at
  ON strategic_selector_decisions(decided_at DESC);

-- Tier 2: Quote Filter per-quote decisions (1 AI fast gate)
CREATE TABLE IF NOT EXISTS quote_filter_decisions (
  id BIGSERIAL PRIMARY KEY,
  quote_id BIGINT,
  decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  model TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('GO', 'SKIP', 'TIMEOUT')),
  confidence REAL,
  brief_reason TEXT,
  latency_ms INT
);
CREATE INDEX IF NOT EXISTS idx_qfd_quote ON quote_filter_decisions(quote_id);
CREATE INDEX IF NOT EXISTS idx_qfd_decided_at
  ON quote_filter_decisions(decided_at DESC);

-- Tier 3: Drawdown Guardian event-driven alerts (3-AI ensemble, alert only)
CREATE TABLE IF NOT EXISTS drawdown_guardian_alerts (
  id BIGSERIAL PRIMARY KEY,
  trade_id BIGINT REFERENCES trades(id),
  alerted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  mtm_pct REAL NOT NULL,
  recommendation TEXT NOT NULL CHECK (recommendation IN ('HOLD', 'MANUAL_EXIT')),
  votes JSONB NOT NULL DEFAULT '{}'::jsonb,
  reasoning TEXT,
  user_action TEXT,
  user_action_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_dga_trade ON drawdown_guardian_alerts(trade_id);
CREATE INDEX IF NOT EXISTS idx_dga_alerted_at
  ON drawdown_guardian_alerts(alerted_at DESC);

-- Quote lifecycle: every maker quote tracked from placement to resolution
CREATE TABLE IF NOT EXISTS quotes (
  id BIGSERIAL PRIMARY KEY,
  market_id TEXT NOT NULL,
  token_id TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
  price NUMERIC(6,4) NOT NULL,
  size_usd NUMERIC(10,2) NOT NULL,
  shares NUMERIC(12,4) NOT NULL,
  spread_bps_at_placement INT,
  fair_price_at_placement NUMERIC(6,4),
  phase TEXT CHECK (phase IN ('early', 'collapse', 'final')),
  trading_mode TEXT,
  clob_order_id TEXT,
  nonce BIGINT,
  status TEXT NOT NULL CHECK (status IN
    ('placed','filled','partial','cancelled','expired','rejected')),
  placed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  filled_at TIMESTAMPTZ,
  cancelled_at TIMESTAMPTZ,
  cancel_reason TEXT,
  filled_pct REAL,
  rebate_credited_usd NUMERIC(8,4),
  trade_id BIGINT REFERENCES trades(id)
);
CREATE INDEX IF NOT EXISTS idx_quotes_market ON quotes(market_id);
CREATE INDEX IF NOT EXISTS idx_quotes_status_placed
  ON quotes(status, placed_at DESC);
CREATE INDEX IF NOT EXISTS idx_quotes_clob_order_id
  ON quotes(clob_order_id) WHERE clob_order_id IS NOT NULL;

-- Rebate ledger: 20% of taker counterparty fee on each maker fill
CREATE TABLE IF NOT EXISTS rebate_accrual (
  id BIGSERIAL PRIMARY KEY,
  quote_id BIGINT REFERENCES quotes(id),
  trade_id BIGINT REFERENCES trades(id),
  accrued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  market_id TEXT NOT NULL,
  category TEXT NOT NULL,
  taker_fee_usd NUMERIC(8,4) NOT NULL,
  rebate_share_pct REAL NOT NULL,
  rebate_usd NUMERIC(8,4) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rebate_accrued
  ON rebate_accrual(accrued_at DESC);
CREATE INDEX IF NOT EXISTS idx_rebate_market
  ON rebate_accrual(market_id);

-- Anti-toxic-flow circuit breaker events
CREATE TABLE IF NOT EXISTS anti_toxic_events (
  id BIGSERIAL PRIMARY KEY,
  triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  market_id TEXT NOT NULL,
  trigger TEXT NOT NULL CHECK (trigger IN
    ('sweep','btc_drift','book_empty','spread_blow','adverse_streak')),
  context JSONB,
  quotes_cancelled INT NOT NULL DEFAULT 0,
  cooldown_until TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_atx_market_time
  ON anti_toxic_events(market_id, triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_atx_trigger
  ON anti_toxic_events(trigger);

-- Geo-block monitoring: poll Polymarket /api/geoblock periodically
CREATE TABLE IF NOT EXISTS geo_block_checks (
  id BIGSERIAL PRIMARY KEY,
  checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  vps_ip INET,
  status TEXT NOT NULL CHECK (status IN
    ('open','trading_restricted','hold_only','fully_blocked','error')),
  raw_response JSONB
);
CREATE INDEX IF NOT EXISTS idx_geo_checked
  ON geo_block_checks(checked_at DESC);

-- system_state: extend with maker tracking columns
ALTER TABLE system_state
  ADD COLUMN IF NOT EXISTS maker_quotes_active INT DEFAULT 0,
  ADD COLUMN IF NOT EXISTS maker_volume_24h_usd NUMERIC(12,2) DEFAULT 0,
  ADD COLUMN IF NOT EXISTS rebate_accrued_24h_usd NUMERIC(8,4) DEFAULT 0,
  ADD COLUMN IF NOT EXISTS rebate_accrued_total_usd NUMERIC(10,4) DEFAULT 0,
  ADD COLUMN IF NOT EXISTS strategic_mode_current TEXT,
  ADD COLUMN IF NOT EXISTS strategic_mode_updated_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS clob_v2_pusd_balance NUMERIC(12,4),
  ADD COLUMN IF NOT EXISTS clob_v2_usdc_balance NUMERIC(12,4),
  ADD COLUMN IF NOT EXISTS geo_block_status TEXT,
  ADD COLUMN IF NOT EXISTS geo_block_last_check TIMESTAMPTZ;

-- trades: link back to source quote + track rebate + placement context
ALTER TABLE trades
  ADD COLUMN IF NOT EXISTS quote_id BIGINT REFERENCES quotes(id),
  ADD COLUMN IF NOT EXISTS rebate_usd NUMERIC(8,4) DEFAULT 0,
  ADD COLUMN IF NOT EXISTS placement_phase TEXT,
  ADD COLUMN IF NOT EXISTS strategic_mode_at_placement TEXT;

-- Seed strategy_performance rows for v4 maker strategies
INSERT INTO strategy_performance (strategy, total_trades, winning_trades, total_pnl, avg_edge, enabled)
  VALUES ('maker_btc_15m', 0, 0, 0, 0, false),
         ('maker_btc_1h',  0, 0, 0, 0, false)
  ON CONFLICT (strategy) DO NOTHING;

-- Expand trades.strategy CHECK to include v3 archived + v4 maker strategies.
-- Idempotent: DROP IF EXISTS + ADD with NOT VALID skips re-validation against
-- existing rows.
ALTER TABLE trades DROP CONSTRAINT IF EXISTS trades_strategy_check;
ALTER TABLE trades ADD CONSTRAINT trades_strategy_check CHECK (
  strategy = ANY (ARRAY[
    'arbitrage','snipe','forecast','market_maker','mean_reversion',
    'cross_venue','political','news_catalyst','live_game','weather',
    'phantom','whale',
    -- v3 archived (moved to _archived-strategies)
    'mispricing_detector','news_conditioned','long_tail_sniper',
    -- v4 maker
    'maker_btc_5m','maker_btc_15m','maker_btc_1h',
    -- v5 ORACLE GAP (information-arbitrage, multi-source synthesis)
    'oracle_gap'
  ])
) NOT VALID;

-- Expand trades.exit_reason CHECK: legacy data has 'zombie_timeout',
-- v4 adds 'manual_exit' (Drawdown Guardian alert), 'geo_block_freeze',
-- 'final_phase_close' (anti-toxic / final-phase quote cancel).
ALTER TABLE trades DROP CONSTRAINT IF EXISTS trades_exit_reason_check;
ALTER TABLE trades ADD CONSTRAINT trades_exit_reason_check CHECK (
  exit_reason = ANY (ARRAY[
    'resolution','early_exit','stop_loss','take_profit','time_stop',
    'arb_ttl_expired',
    'zombie_timeout','manual_exit','geo_block_freeze','final_phase_close'
  ])
) NOT VALID;

-- ════════════════════════════════════════════════════════════════════════
-- SPECTRIX v5 — ORACLE GAP (information-arbitrage, multi-source synthesis)
-- Added 2026-06-01. Shadow-first: nothing here trades until a category
-- graduates via CalibrationGate. See docs/SPECTRIX_5_ORACLE_GAP.md.
-- ════════════════════════════════════════════════════════════════════════

-- 1. Raw external-feed observations (the "truth" side of every divergence).
--    entity_key maps an observation to a Polymarket market candidate.
--    ttl_s + observed_at are the anti-look-ahead guard (R1): a divergence
--    may only use observations whose observed_at predates the signal and
--    whose age < ttl_s.
CREATE TABLE IF NOT EXISTS external_observations (
    id            BIGSERIAL PRIMARY KEY,
    feed_source   TEXT NOT NULL,                 -- 'sports_odds','fedwatch','fred','noaa','kalshi_quote'
    category      TEXT NOT NULL,                 -- 'sports','macro','politics','weather'
    entity_key    TEXT NOT NULL,                 -- join key to a Polymarket market (e.g. event id / ticker)
    observed_prob NUMERIC(6,4),                  -- normalized probability when applicable
    observed_value NUMERIC,                      -- raw numeric (rate, temp, score) when prob N/A
    raw_json      JSONB NOT NULL DEFAULT '{}',
    ttl_s         INT NOT NULL DEFAULT 300,      -- freshness budget for this feed
    observed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_extobs_entity ON external_observations(entity_key, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_extobs_feed   ON external_observations(feed_source, observed_at DESC);

-- 2. Candidate Polymarket markets eligible for ORACLE GAP (objective
--    resolution, medium duration, liquid, mapped to an external feed).
CREATE TABLE IF NOT EXISTS oracle_markets (
    polymarket_id    TEXT PRIMARY KEY,
    question         TEXT NOT NULL,
    category         TEXT NOT NULL,
    feed_mapping     JSONB NOT NULL DEFAULT '{}', -- {feed_source: entity_key, ...}
    resolution_time  TIMESTAMPTZ,
    liquidity_usd    NUMERIC(14,2),
    objective_source TEXT,                        -- the public source the market resolves on
    eligible         BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_oraclemkt_cat ON oracle_markets(category, eligible);

-- 3. Every divergence the engine detects. Edge is ALWAYS computed against
--    the executable CLOB ask, net of fee + slippage — never Gamma bid/mid
--    (that was the v1-v4 phantom-profit trap).
CREATE TABLE IF NOT EXISTS oracle_divergences (
    id                 BIGSERIAL PRIMARY KEY,
    decided_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    polymarket_id      TEXT NOT NULL,
    category           TEXT NOT NULL,
    side               TEXT CHECK (side IN ('YES','NO')),
    external_fair_prob NUMERIC(6,4) NOT NULL,
    poly_executable_ask NUMERIC(6,4) NOT NULL,    -- top-of-book ask actually fillable
    fee_est            NUMERIC(8,4) NOT NULL DEFAULT 0,
    slippage_est       NUMERIC(8,4) NOT NULL DEFAULT 0,
    edge_pp            NUMERIC(7,3) NOT NULL,      -- (fair - ask - fee - slip) * 100
    feed_sources       JSONB NOT NULL DEFAULT '{}',-- {feed: {prob, observed_at, age_s}}
    would_trade_bool   BOOLEAN NOT NULL DEFAULT FALSE,
    shadow_mode        BOOLEAN NOT NULL DEFAULT TRUE,
    max_feed_age_s     INT                         -- staleness of the freshest feed used (R1 audit)
);
CREATE INDEX IF NOT EXISTS idx_oracledv_market ON oracle_divergences(polymarket_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_oracledv_cat    ON oracle_divergences(category, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_oracledv_would  ON oracle_divergences(would_trade_bool, decided_at DESC);

-- 4. Forward, out-of-sample resolution of each would-trade divergence.
--    This is the heart of shadow-first: it records what ACTUALLY happened,
--    so calibration is measured on real outcomes, not a synthetic backtest.
CREATE TABLE IF NOT EXISTS shadow_resolutions (
    id                 BIGSERIAL PRIMARY KEY,
    divergence_id      BIGINT NOT NULL REFERENCES oracle_divergences(id),
    entity_key         TEXT,                      -- = divergence polymarket_id (sport:event:outcome)
    category           TEXT NOT NULL,
    predicted_prob     NUMERIC(6,4) NOT NULL,     -- our external_fair_prob at signal time
    poly_ask_at_signal NUMERIC(6,4) NOT NULL,
    edge_pp_predicted  NUMERIC(7,3) NOT NULL,
    resolved_outcome   INT CHECK (resolved_outcome IN (0,1)),  -- did the bet side win?
    edge_pp_realized   NUMERIC(7,3),              -- realized PnL edge in pp (incl. friction)
    edge_decay_curve   JSONB,                     -- [{t_offset_s, poly_ask}] — how fast it closed
    signal_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at        TIMESTAMPTZ
);
-- Idempotent column add for already-created DBs.
ALTER TABLE shadow_resolutions ADD COLUMN IF NOT EXISTS entity_key TEXT;
CREATE INDEX IF NOT EXISTS idx_shadowres_cat  ON shadow_resolutions(category, resolved_at DESC);
CREATE INDEX IF NOT EXISTS idx_shadowres_div  ON shadow_resolutions(divergence_id);
-- DEDUP GUARD (debug fix 2026-06-01): exactly ONE shadow_resolution per
-- (event, outcome). Without this, the same prediction is re-inserted every
-- poll tick and counted N times in the Brier — inflating the sample and
-- falsifying calibration (the gate to live). UPSERT keys on entity_key.
CREATE UNIQUE INDEX IF NOT EXISTS idx_shadowres_entity ON shadow_resolutions(entity_key);

-- 5. Per-category calibration verdict. A category may only go LIVE when it
--    graduates: Brier < threshold AND n >= min AND realized edge > 0 AND
--    reliability monotone. Recomputed by CalibrationGate from shadow_resolutions.
CREATE TABLE IF NOT EXISTS category_calibration (
    category           TEXT PRIMARY KEY,
    n_observations     INT NOT NULL DEFAULT 0,
    brier_score        NUMERIC(6,4),              -- lower = better calibrated
    reliability_bins   JSONB NOT NULL DEFAULT '[]',-- [{bin, predicted, actual, n}] reliability diagram
    edge_realized_mean NUMERIC(7,3),
    monotone           BOOLEAN NOT NULL DEFAULT FALSE,
    graduated          BOOLEAN NOT NULL DEFAULT FALSE,
    graduated_at       TIMESTAMPTZ,
    last_evaluated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. Health/latency of every external feed (dashboard + auto-pause).
CREATE TABLE IF NOT EXISTS feed_health (
    feed_source   TEXT PRIMARY KEY,
    last_ok_at    TIMESTAMPTZ,
    latency_ms    INT,
    error_streak  INT NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'unknown' CHECK (status IN ('ok','degraded','down','unknown')),
    last_updated  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed the per-category calibration rows (all start un-graduated → no live trading).
INSERT INTO category_calibration (category)
  VALUES ('sports'), ('macro'), ('politics'), ('weather')
  ON CONFLICT (category) DO NOTHING;

-- 7. Goal-Lag Stopwatch (2026-06-11, spec docs/superpowers/specs/
--    2026-06-11-goal-lag-stopwatch-design.md). Model-free measurement of how
--    long Polymarket takes to reprice a goal: ESPN score change → burst-poll
--    of the matched Polymarket win-market → convergence curve. Shadow only.
CREATE TABLE IF NOT EXISTS goal_lag_events (
    id             BIGSERIAL PRIMARY KEY,
    detected_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type     TEXT NOT NULL CHECK (event_type IN ('goal','var_reversal')),
    league         TEXT NOT NULL,             -- 'worldcup' (extensible)
    espn_event_id  TEXT NOT NULL,
    matchup        TEXT,                      -- "South Africa @ Mexico"
    score_before   TEXT,                      -- "0-0" (home-away)
    score_after    TEXT,                      -- "1-0"
    period         INT,
    clock          TEXT,
    poly_condition_id TEXT,
    poly_title     TEXT,
    price_before   NUMERIC(6,4),              -- home-win price pre-goal (≤25s stale)
    curve          JSONB NOT NULL DEFAULT '[]', -- [{t, price}] t = secs since goal
    curve_complete BOOLEAN NOT NULL DEFAULT FALSE,
    interrupted    BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_goallag_detected ON goal_lag_events(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_goallag_event ON goal_lag_events(espn_event_id);
-- M5: dedup against false triggers (restart / scoreboard flap)
CREATE UNIQUE INDEX IF NOT EXISTS idx_goallag_dedup
  ON goal_lag_events(espn_event_id, score_after, event_type);

-- 8. Lag Microscope (2026-06-11, spec 2026-06-11-lag-microscope-design.md).
--    Per-live-game WSS tick recording (CLOB market channel, no auth) + Poisson
--    fair value: turns the goal-lag curves into sub-second, executable-ask,
--    edge-quantified measurements. Shadow only.
CREATE TABLE IF NOT EXISTS live_sessions (
    id            BIGSERIAL PRIMARY KEY,
    espn_event_id TEXT NOT NULL,
    condition_id  TEXT NOT NULL,
    token_yes     TEXT NOT NULL,
    matchup       TEXT,
    poly_title    TEXT,
    lambda_home   NUMERIC(6,3),
    lambda_away   NUMERIC(6,3),
    started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at      TIMESTAMPTZ,
    status        TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','ended','error'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_livesess_active
  ON live_sessions(espn_event_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS live_ticks (
    id          BIGSERIAL PRIMARY KEY,
    session_id  BIGINT NOT NULL REFERENCES live_sessions(id),
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- receive-time locale (M4)
    exchange_ts TIMESTAMPTZ,                          -- server ts del msg WSS
    asset_id    TEXT,
    source      TEXT NOT NULL CHECK (source IN ('book','price_change','trade','espn')),
    best_bid    NUMERIC(6,4),
    best_ask    NUMERIC(6,4),
    trade_price NUMERIC(6,4),
    trade_size  NUMERIC(14,4),
    trade_side  TEXT,
    home_score  INT,
    away_score  INT,
    clock       TEXT,
    fair_home_prob NUMERIC(6,4)
);
CREATE INDEX IF NOT EXISTS idx_liveticks_sess_ts ON live_ticks(session_id, ts);

-- 9. BTC ladder fair-value (2026-06-12, the retail-survivable BTC angle):
--    Deribit options-implied P(BTC>K) vs Polymarket "above $X on <date>".
--    Shadow: btc_divergences = the time series, btc_shadow_trades = one entry
--    per signal, resolved at expiry → honest realized edge before any money.
CREATE TABLE IF NOT EXISTS btc_divergences (
    id            BIGSERIAL PRIMARY KEY,
    decided_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    condition_id  TEXT NOT NULL,
    question      TEXT,
    strike        NUMERIC(12,2),
    poly_prob     NUMERIC(6,4),
    deribit_prob  NUMERIC(6,4),
    gap_pp        NUMERIC(7,3),         -- (deribit - poly) * 100
    spot          NUMERIC(12,2),
    iv_used       NUMERIC(7,3),
    expiry_mismatch_h NUMERIC(6,2),
    resolution_dt TIMESTAMPTZ,
    liquidity     NUMERIC(14,2),
    would_trade   BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_btcdiv_cond ON btc_divergences(condition_id, decided_at DESC);

CREATE TABLE IF NOT EXISTS btc_shadow_trades (
    condition_id   TEXT PRIMARY KEY,
    question       TEXT,
    strike         NUMERIC(12,2),
    entry_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    side           TEXT CHECK (side IN ('YES','NO')),
    entry_poly_prob NUMERIC(6,4),        -- YES price at entry
    entry_cost     NUMERIC(6,4),         -- price paid for the chosen side
    deribit_prob   NUMERIC(6,4),
    gap_pp         NUMERIC(7,3),
    resolution_dt  TIMESTAMPTZ,
    resolved_outcome_yes INT CHECK (resolved_outcome_yes IN (0,1)),
    realized_edge_pp NUMERIC(7,3),       -- gross PnL per share × 100 (pre-fee)
    resolved_at    TIMESTAMPTZ
);
