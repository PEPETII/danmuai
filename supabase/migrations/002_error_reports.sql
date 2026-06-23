-- Automatic error reports from DanmuAI Web console (insert-only for anon).

create table public.error_reports (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null,
  summary text not null check (char_length(summary) between 1 and 500),
  logs_excerpt text check (logs_excerpt is null or char_length(logs_excerpt) <= 8000),
  diagnostics_json jsonb,
  error_fingerprint text,
  app_version text,
  platform text default 'windows',
  locale text,
  created_at timestamptz not null default now()
);

create index error_reports_client_created_idx
  on public.error_reports (client_id, created_at desc);

create index error_reports_fingerprint_idx
  on public.error_reports (error_fingerprint, created_at desc)
  where error_fingerprint is not null;

alter table public.error_reports enable row level security;

create or replace function public.error_reports_insert_allowed(p_client_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select count(*)::int < 3
  from public.error_reports
  where client_id = p_client_id
    and created_at > now() - interval '3 hours';
$$;

create policy "anon_insert_error_reports"
  on public.error_reports
  for insert
  to anon
  with check (
    client_id is not null
    and public.error_reports_insert_allowed(client_id)
  );

create or replace function public.error_reports_quota(p_client_id uuid)
returns json
language plpgsql
stable
security definer
set search_path = public
as $$
declare
  v_limit int := 3;
  v_used int;
  v_oldest timestamptz;
begin
  if p_client_id is null then
    return json_build_object(
      'used', 0,
      'limit', v_limit,
      'remaining', v_limit,
      'window_hours', 3,
      'resets_hint', '请刷新页面后重试'
    );
  end if;

  select count(*)::int, min(created_at)
  into v_used, v_oldest
  from public.error_reports
  where client_id = p_client_id
    and created_at > now() - interval '3 hours';

  return json_build_object(
    'used', v_used,
    'limit', v_limit,
    'remaining', greatest(0, v_limit - v_used),
    'window_hours', 3,
    'resets_hint', case
      when v_used >= v_limit and v_oldest is not null then
        '最近 3 小时内自动错误反馈已达上限，约 ' ||
        to_char(v_oldest + interval '3 hours', 'YYYY-MM-DD HH24:MI') ||
        ' 后可再提交，或使用侧栏「问题反馈」'
      else
        '每 3 小时最多自动提交 ' || v_limit::text || ' 条错误报告'
    end
  );
end;
$$;

grant execute on function public.error_reports_quota(uuid) to anon;
