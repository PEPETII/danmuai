-- Remote tutorial video link (read by anon when enabled).
-- Maintain one enabled row with kind='video'; replace url with https://... when ready.

create table public.tutorial_links (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('video')),
  url text not null,
  enabled boolean not null default true,
  updated_at timestamptz not null default now()
);

create index tutorial_links_kind_enabled_updated_idx
  on public.tutorial_links (kind, enabled, updated_at desc);

alter table public.tutorial_links enable row level security;

create policy "anon_read_enabled_tutorial_links"
  on public.tutorial_links
  for select
  to anon
  using (enabled = true);

insert into public.tutorial_links (kind, url, enabled)
values ('video', '正在紧急赶制中...', true);
