"""Resolve Supabase URL + anon key for server-side PostgREST reads."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.bundle_paths import resource_path
from app.env_config import get as get_env

_URL_RE = re.compile(r"""url:\s*['"]([^'"]+)['"]""")
_ANON_KEY_RE = re.compile(r"""anonKey:\s*['"]([^'"]+)['"]""")


@dataclass(frozen=True)
class SupabaseCredentials:
    url: str
    anon_key: str


def _parse_supabase_config_js(text: str) -> SupabaseCredentials | None:
    if "YOUR_PROJECT" in text:
        return None
    url_match = _URL_RE.search(text)
    key_match = _ANON_KEY_RE.search(text)
    if not url_match or not key_match:
        return None
    url = url_match.group(1).strip().rstrip("/")
    anon_key = key_match.group(1).strip()
    if not url or not anon_key:
        return None
    return SupabaseCredentials(url=url, anon_key=anon_key)


def get_supabase_credentials() -> SupabaseCredentials | None:
    """Env vars override bundled ``web/static/supabase-config.js`` when present."""
    env_url = get_env("DANMU_SUPABASE_URL").strip().rstrip("/")
    env_key = get_env("DANMU_SUPABASE_ANON_KEY").strip()
    if env_url and env_key and "YOUR_PROJECT" not in env_url:
        return SupabaseCredentials(url=env_url, anon_key=env_key)

    config_path = resource_path("web", "static", "supabase-config.js")
    if not config_path.is_file():
        return None
    try:
        return _parse_supabase_config_js(config_path.read_text(encoding="utf-8"))
    except OSError:
        return None
