/** Copy to supabase-config.js and fill in your Supabase project credentials.
 *  Do not commit supabase-config.js (add to .gitignore if missing).
 *  Used for announcements, feedback, error_reports, and backend GET /api/update/channels
 *  (reads app_updates). Optional env override: DANMU_SUPABASE_URL / DANMU_SUPABASE_ANON_KEY. */
window.DANMU_SUPABASE = {
  url: 'https://YOUR_PROJECT_REF.supabase.co',
  anonKey: 'YOUR_ANON_OR_PUBLISHABLE_KEY',
};
