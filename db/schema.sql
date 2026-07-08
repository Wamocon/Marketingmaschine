-- WAMOCON Marketing-Maschine core persistence schema.
-- Intended for PostgreSQL. Add pgvector later when semantic evidence search is enabled.

create table if not exists evidence_items (
  id text primary key,
  claim text not null,
  source_type text not null,
  source_ref text not null,
  approved_for_public_use boolean not null default false,
  consent_ref text,
  owner text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists content_briefs (
  id text primary key,
  campaign text not null,
  persona text not null,
  channel text not null,
  format text not null,
  objective text not null,
  cta text not null,
  proof_sources jsonb not null default '[]'::jsonb,
  utm jsonb not null default '{}'::jsonb,
  hypothesis text not null,
  test_variable text not null,
  status text not null,
  risk_flags jsonb not null default '[]'::jsonb,
  hashtags jsonb not null default '[]'::jsonb,
  trend_id text,
  trend_summary text,
  trend_sources jsonb not null default '[]'::jsonb,
  reel_concept jsonb not null default '{}'::jsonb,
  user_prompt text,
  draft text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists approval_records (
  id bigserial primary key,
  content_id text not null references content_briefs(id),
  reviewer text not null,
  decision text not null,
  brand_score integer not null check (brand_score between 0 and 100),
  fact_check_passed boolean not null default false,
  privacy_check_passed boolean not null default false,
  ai_disclosure_check_passed boolean not null default false,
  notes text,
  created_at timestamptz not null default now()
);

create table if not exists experiment_records (
  id text primary key,
  hypothesis text not null,
  variable text not null,
  campaign text not null,
  persona text not null,
  status text not null default 'running',
  decision text not null default 'wait_for_more_data',
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists performance_records (
  id bigserial primary key,
  content_id text not null references content_briefs(id),
  review_window text not null,
  impressions integer not null default 0,
  saves integer not null default 0,
  shares integer not null default 0,
  comments_from_target_buyers integer not null default 0,
  profile_visits integer not null default 0,
  clicks integer not null default 0,
  leads integer not null default 0,
  qualified_leads integer not null default 0,
  booked_calls integer not null default 0,
  pipeline_value_eur numeric(12,2) not null default 0,
  landing_page_visits integer not null default 0,
  landing_page_conversions integer not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists lead_records (
  id text primary key,
  source_content_id text references content_briefs(id),
  campaign text not null,
  offer text not null,
  persona text not null,
  utm jsonb not null default '{}'::jsonb,
  consent_given boolean not null default false,
  company text,
  email text,
  contact_name text,
  phone text,
  message text,
  qualification_score integer not null default 0,
  next_action text not null default 'review',
  source_verified boolean not null default false,
  routing_allowed boolean not null default false,
  risk_flags jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists routing_outbox (
  id text primary key,
  kind text not null,
  target text not null,
  source_id text not null,
  status text not null,
  dry_run boolean not null default true,
  reason text,
  payload jsonb not null default '{}'::jsonb,
  response jsonb not null default '{}'::jsonb,
  config jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists trend_research_runs (
  id text primary key,
  status text not null,
  run_started_at timestamptz not null,
  lookback_days integer not null default 10,
  lookback_start timestamptz not null,
  platforms jsonb not null default '[]'::jsonb,
  source_adapters jsonb not null default '[]'::jsonb,
  guardrails jsonb not null default '[]'::jsonb,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists trend_signals (
  id text primary key,
  run_id text not null references trend_research_runs(id),
  campaign_id text not null,
  campaign_name text not null,
  topic text not null,
  angle text not null,
  platforms jsonb not null default '[]'::jsonb,
  source_urls jsonb not null default '[]'::jsonb,
  evidence jsonb not null default '[]'::jsonb,
  verification jsonb not null default '{}'::jsonb,
  score integer not null default 0,
  reel_hooks jsonb not null default '[]'::jsonb,
  format_suggestions jsonb not null default '[]'::jsonb,
  creative_notes jsonb not null default '[]'::jsonb,
  hashtags jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists reel_concepts (
  id text primary key,
  run_id text not null references trend_research_runs(id),
  campaign_id text not null,
  trend_id text not null,
  status text not null default 'draft',
  user_prompt text,
  variants jsonb not null default '[]'::jsonb,
  approved_variant_id text,
  content_id text references content_briefs(id),
  guardrails jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists learning_records (
  id bigserial primary key,
  event text not null,
  content_id text references content_briefs(id),
  campaign_id text,
  trend_id text,
  concept_id text references reel_concepts(id),
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists audit_log (
  id bigserial primary key,
  agent_id text not null,
  tool_name text not null,
  action text not null,
  policy_name text not null,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_content_briefs_campaign on content_briefs(campaign);
create index if not exists idx_content_briefs_status on content_briefs(status);
create index if not exists idx_performance_content_window on performance_records(content_id, review_window);
create index if not exists idx_leads_campaign on lead_records(campaign);
create index if not exists idx_leads_next_action on lead_records(next_action);
create index if not exists idx_routing_outbox_source on routing_outbox(source_id);
create index if not exists idx_routing_outbox_status on routing_outbox(status);
create index if not exists idx_trend_signals_run on trend_signals(run_id);
create index if not exists idx_trend_signals_campaign on trend_signals(campaign_id);
create index if not exists idx_reel_concepts_run on reel_concepts(run_id);
create index if not exists idx_reel_concepts_campaign on reel_concepts(campaign_id);
create index if not exists idx_learning_content on learning_records(content_id);
create index if not exists idx_audit_agent_action on audit_log(agent_id, action);
