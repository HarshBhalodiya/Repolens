-- ============================================================
-- RepoLens - Supabase cache table schema
-- Run this in the Supabase SQL editor: Dashboard > SQL > New query
--
-- The UNIQUE constraint on commit_hash is required for the
-- PostgREST `on_conflict=commit_hash` upsert used by db_client.py.
-- ============================================================

create table if not exists public.repo_analysis (
    id            bigint generated always as identity primary key,
    repo_path     text not null,
    commit_hash   text not null unique,
    analysis_data jsonb not null,
    cached_at     timestamptz not null default now()
);

-- Index for fast lookups by commit hash
create index if not exists repo_analysis_commit_hash_idx
    on public.repo_analysis (commit_hash);

-- ------------------------------------------------------------
-- Row Level Security
--
-- The service-role key bypasses RLS entirely, so db_client.py's writes
-- keep working unaffected if you use that key. The previous version of
-- these policies used `using (true)` / `with check (true)` for insert and
-- update, which means: if this table is ever accessed with the *anon* key
-- (e.g. that key leaks, or a future client calls Supabase directly), ANY
-- caller could insert or overwrite ANY row, including rows for repos they
-- don't own -- i.e. cache poisoning. Reads stay open (cached analysis
-- data isn't sensitive), but writes now require the service role.
-- ------------------------------------------------------------
alter table public.repo_analysis enable row level security;

create policy "repo_analysis_read" on public.repo_analysis
    for select using (true);

create policy "repo_analysis_insert" on public.repo_analysis
    for insert with check (auth.role() = 'service_role');

create policy "repo_analysis_update" on public.repo_analysis
    for update using (auth.role() = 'service_role')
    with check (auth.role() = 'service_role');
