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

-- ============================================================
-- RAG codebase chat: code_embeddings table + match RPC
--
-- BUGFIX: app/rag_indexer.py and app/ai_engine.py depend on these,
-- but they were never in this file. Without them, indexing writes
-- fail (table missing) and chat can never retrieve any context -
-- this is why /api/chat always said "Please index the codebase
-- first." Run this block in the Supabase SQL editor.
-- ============================================================

create extension if not exists vector;

create table if not exists public.code_embeddings (
    id         bigint generated always as identity primary key,
    repo_path  text not null,
    file_path  text not null,
    content    text not null,
    embedding  vector(384) not null,  -- all-MiniLM-L6-v2 output size
    created_at timestamptz not null default now()
);

create index if not exists code_embeddings_repo_path_idx
    on public.code_embeddings (repo_path);

-- ivfflat index for fast cosine-similarity search
create index if not exists code_embeddings_embedding_idx
    on public.code_embeddings using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

alter table public.code_embeddings enable row level security;

create policy "code_embeddings_read" on public.code_embeddings
    for select using (true);

create policy "code_embeddings_insert" on public.code_embeddings
    for insert with check (auth.role() = 'service_role');

create policy "code_embeddings_delete" on public.code_embeddings
    for delete using (auth.role() = 'service_role');

-- Matches app/ai_engine.py's call:
--   rpc/match_code_embeddings {query_embedding, match_threshold, match_count, filter_repo_path}
create or replace function public.match_code_embeddings(
    query_embedding vector(384),
    match_threshold float,
    match_count int,
    filter_repo_path text
)
returns table (
    id bigint,
    file_path text,
    content text,
    similarity float
)
language sql stable
as $$
    select
        id,
        file_path,
        content,
        1 - (embedding <=> query_embedding) as similarity
    from public.code_embeddings
    where repo_path = filter_repo_path
        and 1 - (embedding <=> query_embedding) > match_threshold
    order by embedding <=> query_embedding
    limit match_count;
$$;
