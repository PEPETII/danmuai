"""Application release version — single source for local build identity.

Format: semver vx.x.x (stored without leading v; e.g. v0.2.2 → 0.2.2).
Align with Git tag and Supabase `app_updates.latest_version` on each release.
"""

# 发布时与 Git tag、Supabase app_updates 对齐（vx.x.x，可带或不带 v 前缀）
__version__ = "0.3.2"
