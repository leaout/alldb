import sqlite3
import re
from typing import Any, Dict, List

from .base import AdapterResult, DatabaseAdapter


class SQLiteAdapter(DatabaseAdapter):
    key = "sqlite"
    label = "SQLite"
    capabilities = ["query", "metadata", "write", "export"]

    def _connect(self):
        path = self.config.get("database") or ":memory:"
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        return connection

    def test(self):
        with self._connect() as db:
            version = db.execute("select sqlite_version()").fetchone()[0]
        return {"ok": True, "version": version}

    def objects(self) -> List[Dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT type,name,tbl_name AS parent FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            ).fetchall()
        return [dict(row) for row in rows]

    def execute(self, query, parameters, max_rows):
        with self._connect() as db:
            cursor = db.execute(query, parameters)
            if cursor.description:
                columns = [column[0] for column in cursor.description]
                data = cursor.fetchmany(max_rows + 1)
                truncated = len(data) > max_rows
                rows = [[self._safe(value) for value in row] for row in data[:max_rows]]
                return AdapterResult(columns, rows, len(rows), truncated)
            db.commit()
            return AdapterResult([], [], max(cursor.rowcount, 0), False, f"Affected rows: {max(cursor.rowcount, 0)}")

    def import_rows(self, table, columns, rows):
        names = [table] + columns
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", name) for name in names):
            raise ValueError("Table and column names must be simple identifiers")
        quoted_columns = ",".join('"' + name + '"' for name in columns)
        placeholders = ",".join("?" for _ in columns)
        sql = f'INSERT INTO "{table}" ({quoted_columns}) VALUES ({placeholders})'
        with self._connect() as db:
            db.executemany(sql, rows)
            db.commit()
        return len(rows)

    def overview(self):
        result = super().overview()
        with self._connect() as db:
            result["object_count"] = db.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchone()[0]
            result["size_bytes"] = db.execute("PRAGMA page_count").fetchone()[0] * db.execute("PRAGMA page_size").fetchone()[0]
        return result

    def object_details(self, schema, name):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", name):
            raise ValueError("Invalid object name")
        with self._connect() as db:
            columns = [dict(row) for row in db.execute(f'PRAGMA table_info("{name}")').fetchall()]
            indexes = [dict(row) for row in db.execute(f'PRAGMA index_list("{name}")').fetchall()]
            ddl_row = db.execute("SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()
        return {"schema": "main", "name": name, "columns": columns, "indexes": indexes,
                "ddl": ddl_row[0] if ddl_row and ddl_row[0] else ""}

    def tree(self, node_type="root", database="", schema="", table=""):
        if node_type == "root":
            return [{"id": "main", "name": "main", "type": "database", "database": "main", "has_children": True}]
        if node_type == "database":
            return [{"id": f"main.{item['name']}", "name": item["name"], "type": item["type"],
                     "database": "main", "schema": "main", "table": item["name"], "has_children": True}
                    for item in self.objects() if item["type"] in {"table", "view"}]
        return super().tree(node_type, database, schema, table)

    @staticmethod
    def _safe(value):
        if isinstance(value, bytes):
            return {"$binary": value.hex()}
        return value
