"""万方 adapter (experimental, disabled by default).

Per design §5.2/§15 the 万方 channel is experimental and requires the user's own
`X-App-Key`; the official field contract is not verified. We therefore never
scrape wanfang and never pretend to have results: requesting this source returns
a clear, actionable error instead of fabricated hits.
"""

from __future__ import annotations

import os
from typing import Any

from ...models import SearchHit
from .base import SearchAdapter, SourceError


class WanfangAdapter(SearchAdapter):
    name = "wanfang"
    label = "万方（实验性）"

    def _fetch(
        self,
        query: str,
        *,
        limit: int,
        year_from: int | None,
        year_to: int | None,
        language: str | None,
    ) -> list[Any]:
        if not os.environ.get("WENSHU_WANFANG_APP_KEY"):
            raise SourceError(
                "wanfang",
                "万方通道为实验性功能：需要自备 X-App-Key（环境变量 WENSHU_WANFANG_APP_KEY），"
                "当前未配置，已跳过。可改用 OpenAlex / Crossref / arXiv / 手动导入。",
            )
        raise SourceError(
            "wanfang",
            "万方官方接口字段与商用条款尚未核实，本版本不启用自动检索；"
            "请使用万方官网导出 RIS/NoteExpress 文件后导入。",
        )

    def _to_hit(self, item: Any) -> SearchHit | None:
        return None
