-- Add structured context and logs excerpt to feedback (W-FEEDBACK-CONTEXT-001).

alter table public.feedback
  add column if not exists context_json jsonb,
  add column if not exists logs_excerpt text
    check (logs_excerpt is null or char_length(logs_excerpt) <= 8000);
