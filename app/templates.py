from datetime import datetime

from app.config_store import ConfigStore


class TemplateManager:
    def __init__(self, config: ConfigStore):
        self.config = config

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
