-- Announcements (read by anon when published) and feedback (insert-only for anon).

create table public.announcements (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  body text not null,
  level text not null default 'info'
    check (level in ('info', 'warning', 'critical')),
  published boolean not null default false,
  pinned boolean not null default false,
  starts_at timestamptz,
  ends_at timestamptz,
  created_at timestamptz not null default now()
);

create table public.feedback (
  id uuid primary key default gen_random_uuid(),
  content text not null check (char_length(content) between 1 and 2000),
  contact text check (contact is null or char_length(contact) <= 200),
  client_id uuid not null,
  app_version text,
  platform text default 'windows',
  locale text,
  created_at timestamptz not null default now()
);

create index announcements_published_list_idx
  on public.announcements (published, pinned desc, created_at desc);

create index feedback_client_created_idx
  on public.feedback (client_id, created_at desc);

alter table public.announcements enable row level security;
alter table public.feedback enable row level security;

create policy "anon_read_published_announcements"
  on public.announcements
  for select
  to anon
  using (
    published = true
    and (starts_at is null or starts_at <= now())
    and (ends_at is null or ends_at > now())
  );

create or replace function public.feedback_insert_allowed(p_client_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select count(*)::int < 2
  from public.feedback
  where client_id = p_client_id
    and created_at > now() - interval '3 hours';
$$;

create policy "anon_insert_feedback"
  on public.feedback
  for insert
  to anon
  with check (
    client_id is not null
    and public.feedback_insert_allowed(client_id)
  );

create or replace function public.feedback_quota(p_client_id uuid)
returns json
language plpgsql
stable
security definer
set search_path = public
as $$
declare
  v_limit int := 2;
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
  from public.feedback
  where client_id = p_client_id
    and created_at > now() - interval '3 hours';

  return json_build_object(
    'used', v_used,
    'limit', v_limit,
    'remaining', greatest(0, v_limit - v_used),
    'window_hours', 3,
    'resets_hint', case
      when v_used >= v_limit and v_oldest is not null then
        '最近 3 小时内已达上限，约 ' ||
        to_char(v_oldest + interval '3 hours', 'YYYY-MM-DD HH24:MI') ||
        ' 后可再提交'
      else
        '每 3 小时最多提交 ' || v_limit::text || ' 条'
    end
  );
end;
$$;

grant execute on function public.feedback_quota(uuid) to anon;
