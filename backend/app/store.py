import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .crypto import SecretBox
from .schemas import ConnectionInput


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConnectionStore:
    def __init__(self, path: Path, secrets: SecretBox):
        self.path = path
        self.secrets = secrets
        self._init()

    def _connect(self):
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        return connection

    def _init(self):
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS connections (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, driver TEXT NOT NULL,
                    host TEXT NOT NULL, port INTEGER, database_name TEXT NOT NULL,
                    username TEXT NOT NULL, password_cipher TEXT NOT NULL,
                    options_json TEXT NOT NULL, readonly INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )"""
            )

    def list(self) -> List[Dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM connections ORDER BY name COLLATE NOCASE").fetchall()
        return [self._public(row) for row in rows]

    def get(self, connection_id: str, include_password: bool = False) -> Optional[Dict[str, Any]]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM connections WHERE id = ?", (connection_id,)).fetchone()
        if not row:
            return None
        result = self._public(row)
        if include_password:
            result["password"] = self.secrets.decrypt(row["password_cipher"])
        return result

    def create(self, value: ConnectionInput) -> Dict[str, Any]:
        connection_id = str(uuid.uuid4())
        now = utc_now()
        with self._connect() as db:
            db.execute(
                """INSERT INTO connections
                (id,name,driver,host,port,database_name,username,password_cipher,options_json,readonly,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (connection_id, value.name, value.driver, value.host, value.port, value.database,
                 value.username, self.secrets.encrypt(value.password or ""), json.dumps(value.options),
                 int(value.readonly), now, now),
            )
        return self.get(connection_id)  # type: ignore[return-value]

    def update(self, connection_id: str, value: ConnectionInput) -> Optional[Dict[str, Any]]:
        current = self.get(connection_id, include_password=True)
        if not current:
            return None
        password = current["password"] if value.password is None else value.password
        with self._connect() as db:
            db.execute(
                """UPDATE connections SET name=?,driver=?,host=?,port=?,database_name=?,username=?,
                password_cipher=?,options_json=?,readonly=?,updated_at=? WHERE id=?""",
                (value.name, value.driver, value.host, value.port, value.database, value.username,
                 self.secrets.encrypt(password), json.dumps(value.options), int(value.readonly),
                 utc_now(), connection_id),
            )
        return self.get(connection_id)

    def delete(self, connection_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM connections WHERE id = ?", (connection_id,))
        return cursor.rowcount > 0

    @staticmethod
    def _public(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"], "name": row["name"], "driver": row["driver"],
            "host": row["host"], "port": row["port"], "database": row["database_name"],
            "username": row["username"], "options": json.loads(row["options_json"]),
            "readonly": bool(row["readonly"]), "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

