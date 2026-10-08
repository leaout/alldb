import re
from typing import Any, Dict, List

from .base import AdapterResult, DatabaseAdapter


def safe_value(value):
    if isinstance(value, bytes):
        return {"$binary": value.hex()}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if type(value).__module__ == "decimal":
        return str(value)
    return value


class DBAPIAdapter(DatabaseAdapter):
    placeholder = "%s"
    identifier_quote = '"'

    def connect(self):
        raise NotImplementedError

    def version_sql(self):
        return "SELECT VERSION()"

    def object_sql(self):
        raise NotImplementedError

    def test(self):
        connection = self.connect()
        try:
            cursor = connection.cursor()
            cursor.execute(self.version_sql())
            return {"ok": True, "version": str(cursor.fetchone()[0])}
        finally:
            connection.close()

    def objects(self) -> List[Dict[str, Any]]:
        connection = self.connect()
        try:
            cursor = connection.cursor()
            cursor.execute(self.object_sql())
            return [{"schema": row[0], "name": row[1], "type": row[2]} for row in cursor.fetchall()]
        finally:
            connection.close()

    def execute(self, query, parameters, max_rows):
        connection = self.connect()
        try:
            cursor = connection.cursor()
            cursor.execute(query, parameters or None)
            if cursor.description:
                columns = [item[0] for item in cursor.description]
                data = cursor.fetchmany(max_rows + 1)
                rows = [[safe_value(value) for value in row] for row in data[:max_rows]]
                return AdapterResult(columns, rows, len(rows), len(data) > max_rows)
            connection.commit()
            count = max(cursor.rowcount, 0)
            return AdapterResult([], [], count, False, f"Affected rows: {count}")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def import_rows(self, table, columns, rows):
        identifiers = table.split(".") + columns
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", name) for name in identifiers):
            raise ValueError("Table and column names must be simple identifiers")
        quote = self.identifier_quote
        quoted_table = ".".join(f"{quote}{name}{quote}" for name in table.split("."))
        quoted_columns = ",".join(f"{quote}{name}{quote}" for name in columns)
        sql = f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({','.join(self.placeholder for _ in columns)})"
        connection = self.connect()
        try:
            cursor = connection.cursor()
            cursor.executemany(sql, rows)
            connection.commit()
            return len(rows)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


class MySQLAdapter(DBAPIAdapter):
    key = "mysql"
    label = "MySQL / MariaDB"
    default_port = 3306
    capabilities = ["query", "metadata", "write", "export"]
    identifier_quote = "`"

    def connect(self):
        import pymysql
        return pymysql.connect(host=self.config["host"], port=self.config.get("port") or 3306,
                               user=self.config.get("username"), password=self.config.get("password"),
                               database=self.config.get("database") or None,
                               connect_timeout=int(self.config.get("options", {}).get("connect_timeout", 10)),
                               charset="utf8mb4")

    def object_sql(self):
        return "SELECT table_schema,table_name,table_type FROM information_schema.tables WHERE table_schema=DATABASE() ORDER BY table_name"

    def overview(self):
        result = super().overview()
        connection = self.connect()
        try:
            cursor = connection.cursor()
            cursor.execute("""SELECT COUNT(DISTINCT table_schema),COUNT(*) FROM information_schema.tables
                            WHERE table_schema NOT IN ('information_schema','mysql','performance_schema','sys')""")
            database_count, object_count = cursor.fetchone()
            result.update({"database_count": database_count, "object_count": object_count})
            return result
        finally:
            connection.close()

    def object_details(self, schema, name):
        connection = self.connect()
        schema = schema or self.config.get("database")
        try:
            cursor = connection.cursor()
            cursor.execute("""SELECT column_name,column_type,is_nullable,column_default,column_key,extra
                            FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position""",
                           (schema, name))
            columns = [{"name": r[0], "type": r[1], "nullable": r[2], "default": safe_value(r[3]), "key": r[4], "extra": r[5]} for r in cursor.fetchall()]
            cursor.execute("""SELECT index_name,column_name,non_unique,seq_in_index
                            FROM information_schema.statistics WHERE table_schema=%s AND table_name=%s ORDER BY index_name,seq_in_index""",
                           (schema, name))
            indexes = [{"name": r[0], "column": r[1], "unique": not bool(r[2]), "position": r[3]} for r in cursor.fetchall()]
            safe_schema = str(schema).replace('`', '``')
            safe_name = name.replace('`', '``')
            cursor.execute(f"SHOW CREATE TABLE `{safe_schema}`.`{safe_name}`")
            row = cursor.fetchone()
            return {"schema": schema, "name": name, "columns": columns, "indexes": indexes,
                    "ddl": row[1] if row and len(row) > 1 else ""}
        finally:
            connection.close()

    def tree(self, node_type="root", database="", schema="", table=""):
        connection = self.connect()
        try:
            cursor = connection.cursor()
            if node_type == "root":
                cursor.execute("""SELECT schema_name FROM information_schema.schemata
                                WHERE schema_name NOT IN ('information_schema','mysql','performance_schema','sys')
                                ORDER BY schema_name""")
                return [{"id": f"db:{r[0]}", "name": r[0], "type": "database", "database": r[0], "has_children": True} for r in cursor.fetchall()]
            if node_type == "database":
                cursor.execute("""SELECT table_name,table_type FROM information_schema.tables
                                WHERE table_schema=%s ORDER BY table_name""", (database,))
                return [{"id": f"table:{database}.{r[0]}", "name": r[0],
                         "type": "view" if r[1] == "VIEW" else "table", "database": database,
                         "schema": database, "table": r[0], "has_children": True} for r in cursor.fetchall()]
            if node_type in {"table", "view"}:
                cursor.execute("""SELECT column_name,column_type,column_key,is_nullable
                                FROM information_schema.columns WHERE table_schema=%s AND table_name=%s
                                ORDER BY ordinal_position""", (database or schema, table))
                return [{"id": f"column:{database}.{table}.{r[0]}", "name": r[0], "type": "column",
                         "data_type": r[1], "key": r[2], "nullable": r[3], "has_children": False}
                        for r in cursor.fetchall()]
            return []
        finally:
            connection.close()


class TiDBAdapter(MySQLAdapter):
    key = "tidb"
    label = "TiDB"
    default_port = 4000

    def connect(self):
        import pymysql
        options = self.config.get("options", {})
        ssl = {"ca": options["ssl_ca"]} if options.get("ssl_ca") else None
        return pymysql.connect(host=self.config["host"], port=self.config.get("port") or 4000,
                               user=self.config.get("username"), password=self.config.get("password"),
                               database=self.config.get("database") or None, connect_timeout=10,
                               charset="utf8mb4", ssl=ssl)


class PostgresAdapter(DBAPIAdapter):
    key = "postgresql"
    label = "PostgreSQL"
    default_port = 5432
    capabilities = ["query", "metadata", "write", "export", "schemas"]

    def connect(self):
        import psycopg
        return psycopg.connect(host=self.config["host"], port=self.config.get("port") or 5432,
                               user=self.config.get("username"), password=self.config.get("password"),
                               dbname=self.config.get("database") or "postgres", connect_timeout=10)

    def object_sql(self):
        return "SELECT table_schema,table_name,table_type FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema') ORDER BY table_schema,table_name"

    def object_details(self, schema, name):
        schema = schema or "public"
        connection = self.connect()
        try:
            cursor = connection.cursor()
            cursor.execute("""SELECT column_name,data_type,is_nullable,column_default
                            FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position""",
                           (schema, name))
            columns = [{"name": r[0], "type": r[1], "nullable": r[2], "default": safe_value(r[3])} for r in cursor.fetchall()]
            cursor.execute("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=%s AND tablename=%s ORDER BY indexname", (schema, name))
            indexes = [{"name": r[0], "definition": r[1]} for r in cursor.fetchall()]
            return {"schema": schema, "name": name, "columns": columns, "indexes": indexes, "ddl": ""}
        finally:
            connection.close()

    def tree(self, node_type="root", database="", schema="", table=""):
        connection = self.connect()
        try:
            cursor = connection.cursor()
            current_db = self.config.get("database") or "postgres"
            if node_type == "root":
                return [{"id": f"db:{current_db}", "name": current_db, "type": "database",
                         "database": current_db, "has_children": True}]
            if node_type == "database":
                cursor.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT IN ('pg_catalog','information_schema') ORDER BY schema_name")
                return [{"id": f"schema:{r[0]}", "name": r[0], "type": "schema", "database": current_db,
                         "schema": r[0], "has_children": True} for r in cursor.fetchall()]
            if node_type == "schema":
                cursor.execute("""SELECT table_name,table_type FROM information_schema.tables
                                WHERE table_schema=%s ORDER BY table_name""", (schema,))
                return [{"id": f"table:{schema}.{r[0]}", "name": r[0],
                         "type": "view" if r[1] == "VIEW" else "table", "database": current_db,
                         "schema": schema, "table": r[0], "has_children": True} for r in cursor.fetchall()]
            if node_type in {"table", "view"}:
                cursor.execute("""SELECT column_name,data_type,is_nullable FROM information_schema.columns
                                WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position""", (schema, table))
                return [{"id": f"column:{schema}.{table}.{r[0]}", "name": r[0], "type": "column",
                         "data_type": r[1], "nullable": r[2], "has_children": False} for r in cursor.fetchall()]
            return []
        finally:
            connection.close()
