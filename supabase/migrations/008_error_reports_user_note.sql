-- Optional user context on automatic error reports (W-ERROR-REPORT user note).

alter table public.error_reports
  add column if not exists user_note text
    check (user_note is null or char_length(user_note) between 1 and 1000),
  add column if not exists contact text
    check (contact is null or char_length(contact) <= 200);
