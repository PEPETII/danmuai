from datetime import datetime

from app.config_store import ConfigStore
from app.persona_builtin import LEGACY_NAME_MAP


class TemplateManager:
    def __init__(self, config: ConfigStore):
        self.config = config
        self._migrate_legacy_persona_names()

    def _migrate_legacy_persona_names(self) -> None:
        """将历史模板行迁移到改名后的稳定人格 ID。"""
        with self.config._write_lock:
            for old_name, new_name in LEGACY_NAME_MAP.items():
                old_name = str(old_name or "").strip()
                new_name = str(new_name or "").strip()
                if not old_name or not new_name or old_name == new_name:
                    continue
                rows = self.config.conn.execute(
                    "SELECT system_pt, user_pt, created_at FROM templates "
                    "WHERE name=? ORDER BY id",
                    (old_name,),
                ).fetchall()
                if not rows:
                    continue
                max_row = self.config.conn.execute(
                    "SELECT MAX(version) FROM templates WHERE name=?",
                    (new_name,),
                ).fetchone()
                next_version = int(max_row[0] or 0) + 1
                for system_pt, user_pt, created_at in rows:
                    self.config.conn.execute(
                        "INSERT INTO templates "
                        "(name, version, system_pt, user_pt, created_at) "
                        "VALUES (?,?,?,?,?)",
                        (new_name, next_version, system_pt, user_pt, created_at),
                    )
                    next_version += 1
                self.config.conn.execute(
                    "DELETE FROM templates WHERE name=?",
                    (old_name,),
                )
            self.config.conn.commit()

    def save(self, name: str, system_pt: str, user_pt: str):
        with self.config._write_lock:
            rows = self.config.conn.execute(
                "SELECT MAX(version) FROM templates WHERE name=?", (name,)
            ).fetchone()
            version = (rows[0] or 0) + 1
            self.config.conn.execute(
                "INSERT INTO templates (name, version, system_pt, user_pt, created_at) VALUES (?,?,?,?,?)",
                (name, version, system_pt, user_pt, datetime.now().isoformat()),
            )
            self.config.conn.commit()

    def load(self, name: str, version: int | None = None) -> tuple[str, str]:
        if version:
            row = self.config.conn.execute(
                "SELECT system_pt, user_pt FROM templates WHERE name=? AND version=?",
                (name, version),
            ).fetchone()
        else:
            row = self.config.conn.execute(
                "SELECT system_pt, user_pt FROM templates WHERE name=? ORDER BY version DESC LIMIT 1",
                (name,),
            ).fetchone()
        if row:
            return row[0], row[1]
        return ("", "")

    def versions(self, name: str) -> list[dict]:
        rows = self.config.conn.execute(
            "SELECT version, system_pt, user_pt, created_at FROM templates WHERE name=? ORDER BY version DESC",
            (name,),
        ).fetchall()
        return [
            {"version": r[0], "system_pt": r[1], "user_pt": r[2], "created_at": r[3]}
            for r in rows
        ]

    def render(self, text: str, **kwargs) -> str:
        return text.format(**kwargs)
