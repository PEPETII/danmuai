"""MIME type overrides for Web console static assets.

On Windows, Python's mimetypes module may read HKCR\\.js\\Content Type from the
registry. Some machines map .js to text/plain, which breaks <script type="module">.
"""

from __future__ import annotations

import mimetypes


def ensure_web_static_mime_types() -> None:
    """Override broken OS registry mappings before Starlette serves /static."""
    mimetypes.add_type("application/javascript", ".js", strict=True)
    mimetypes.add_type("text/css", ".css", strict=True)
