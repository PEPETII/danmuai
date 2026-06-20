"""烂梗远程 API 客户端（httpx；认证头 Dpahjdoiaw + Origin）。"""

from __future__ import annotations

from typing import Any

import httpx

from app.meme_barrage.config import normalize_meme_barrage_tags

API_BASE = "https://hguofichp.cn:10086"
API_ORIGIN = "https://hguofichp.cn"

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Dpahjdoiaw": "danmuAi",
    "Origin": API_ORIGIN,
    "Referer": f"{API_ORIGIN}/",
}

def format_tags_for_remote_api(tags: list[str], page_num: int = 1) -> str:
    """Build ``tags`` query param for sortAllBarrage / remote fetch."""
    return ",".join(normalize_meme_barrage_tags(tags))


# Fallback when dictList is unreachable (27 tags from API snapshot).
FALLBACK_TAGS: list[dict[str, str]] = [
    {"value": "00", "label": "喷玩机器"},
    {"value": "01", "label": "喷选手"},
    {"value": "02", "label": "加一"},
    {"value": "03", "label": "QUQU"},
    {"value": "05", "label": "木柜子"},
    {"value": "06", "label": "群魔乱舞"},
    {"value": "07", "label": "NiKo"},
    {"value": "08", "label": "ropz"},
    {"value": "09", "label": "直播间互喷"},
    {"value": "10", "label": "Donk"},
    {"value": "11", "label": "伟伟"},
    {"value": "12", "label": "Zywoo"},
    {"value": "13", "label": "m0NESY"},
    {"value": "14", "label": "丰川祥子"},
    {"value": "15", "label": "device"},
    {"value": "16", "label": "Twistzz"},
    {"value": "17", "label": "DOTA"},
    {"value": "18", "label": "千早爱音"},
    {"value": "19", "label": "三角初华"},
    {"value": "20", "label": "Falcons"},
    {"value": "21", "label": "S1mple"},
    {"value": "22", "label": "赛事梗"},
    {"value": "23", "label": "京介"},
    {"value": "24", "label": "HLTV"},
    {"value": "25", "label": "Team Spirit"},
    {"value": "26", "label": "chopper"},
    {"value": "27", "label": "🗿🗿🗿"},
]


class MemeBarrageApiClient:
    def __init__(self, base_url: str = API_BASE, *, verify_ssl: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self._verify = verify_ssl
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers=DEFAULT_HEADERS,
                verify=self._verify,
                timeout=20.0,
                limits=httpx.Limits(max_keepalive_connections=2, max_connections=4),
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        client = self._get_client()
        resp = client.request(method, url, **kwargs)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("code") not in (None, 200):
            raise RuntimeError(f"API error {data.get('code')}: {data.get('msg')}")
        return data

    def page(self, page_num: int = 1, page_size: int = 5) -> dict[str, Any]:
        return self._request(
            "GET",
            "/machine/Page",
            params={"pageNum": page_num, "pageSize": page_size},
        )

    def sort_all_barrage(
        self,
        page_num: int = 1,
        page_size: int = 5,
        tags: str = "06",
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/machine/sortAllBarrage",
            params={"pageNum": page_num, "pageSize": page_size, "tags": tags},
        )

    def dict_list(self) -> list[dict[str, str]]:
        data = self._request("GET", "/machine/dictList")
        payload = data.get("data") if isinstance(data, dict) else data
        if not isinstance(payload, list):
            return list(FALLBACK_TAGS)
        tags: list[dict[str, str]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            value = str(item.get("dictValue", "") or "").strip()
            label = str(item.get("dictLabel", "") or value).strip()
            if value:
                tags.append({"value": value, "label": label})
        return tags or list(FALLBACK_TAGS)


def parse_barrage_page(data: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """Return list items and whether this is the last page."""
    payload = data.get("data") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        return [], True
    items = payload.get("list")
    if not isinstance(items, list):
        return [], True
    last_page = bool(payload.get("lastPage"))
    return [item for item in items if isinstance(item, dict)], last_page
