-- Remote app update config (read by anon when enabled).
-- After publishing a GitHub Release, maintain one enabled row with latest_version.

create table public.app_updates (
  id uuid primary key default gen_random_uuid(),
  latest_version text not null,
  release_url text not null default 'https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe',
  enabled boolean not null default true,
  message text,
  updated_at timestamptz not null default now()
);

create index app_updates_enabled_updated_idx
  on public.app_updates (enabled, updated_at desc);

alter table public.app_updates enable row level security;

create policy "anon_read_enabled_app_updates"
  on public.app_updates
  for select
  to anon
  using (enabled = true);
