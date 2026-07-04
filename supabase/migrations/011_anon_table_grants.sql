-- BUG-021: Explicit anon table grants — insert-only or read-only per table.
-- RLS policies remain the row-level gate; this migration revokes default broad grants.

-- insert-only
revoke all on public.feedback from anon;
grant insert on public.feedback to anon;

revoke all on public.error_reports from anon;
grant insert on public.error_reports to anon;

-- read-only (RLS policies still constrain rows)
revoke all on public.announcements from anon;
grant select on public.announcements to anon;

revoke all on public.app_updates from anon;
grant select on public.app_updates to anon;

revoke all on public.tutorial_links from anon;
grant select on public.tutorial_links to anon;
