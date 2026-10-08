from .base import AdapterResult, DatabaseAdapter
from .relational import safe_value


class ClickHouseAdapter(DatabaseAdapter):
    key = "clickhouse"
    label = "ClickHouse"
    default_port = 8123
    capabilities = ["query", "metadata", "write", "export"]

    def _client(self):
        import clickhouse_connect
        options = self.config.get("options", {})
        return clickhouse_connect.get_client(
            host=self.config["host"], port=self.config.get("port") or 8123,
            username=self.config.get("username") or "default", password=self.config.get("password") or "",
            database=self.config.get("database") or "default", secure=bool(options.get("secure", False)))

    def test(self):
        client = self._client()
        try:
            return {"ok": True, "version": str(client.command("SELECT version()"))}
        finally:
            client.close()

    def objects(self):
        client = self._client()
        try:
            result = client.query("SELECT database,name,engine FROM system.tables WHERE database=currentDatabase() ORDER BY name")
            return [{"schema": r[0], "name": r[1], "type": r[2]} for r in result.result_rows]
        finally:
            client.close()

    def execute(self, query, parameters, max_rows):
        client = self._client()
        try:
            first = query.lstrip().split(None, 1)[0].upper() if query.strip() else ""
            if first not in {"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "WITH"}:
                message = client.command(query, parameters=parameters)
                return AdapterResult([], [], 0, False, str(message or "Command completed"))
            result = client.query(query, parameters=parameters)
            data = result.result_rows[:max_rows + 1]
            rows = [[safe_value(v) for v in row] for row in data[:max_rows]]
            return AdapterResult(list(result.column_names), rows, len(rows), len(data) > max_rows)
        finally:
            client.close()

    def import_rows(self, table, columns, rows):
        client = self._client()
        try:
            client.insert(table, rows, column_names=columns)
            return len(rows)
        finally:
            client.close()

    def object_details(self, schema, name):
        client = self._client()
        try:
            result = client.query("SELECT name,type,default_kind,default_expression FROM system.columns WHERE database={db:String} AND table={table:String} ORDER BY position",
                                  parameters={"db": schema or self.config.get("database") or "default", "table": name})
            columns = [{"name": r[0], "type": r[1], "default_kind": r[2], "default": r[3]} for r in result.result_rows]
            ddl = str(client.command(f"SHOW CREATE TABLE `{name.replace('`', '``')}`"))
            return {"schema": schema, "name": name, "columns": columns, "indexes": [], "ddl": ddl}
        finally:
            client.close()

    def tree(self, node_type="root", database="", schema="", table=""):
        client = self._client()
        try:
            if node_type == "root":
                rows = client.query("SELECT name FROM system.databases WHERE name NOT IN ('system','information_schema','INFORMATION_SCHEMA') ORDER BY name").result_rows
                return [{"id": f"db:{r[0]}", "name": r[0], "type": "database", "database": r[0], "has_children": True} for r in rows]
            if node_type == "database":
                rows = client.query("SELECT name,engine FROM system.tables WHERE database={db:String} ORDER BY name", parameters={"db": database}).result_rows
                return [{"id": f"table:{database}.{r[0]}", "name": r[0], "type": "view" if "View" in r[1] else "table",
                         "database": database, "schema": database, "table": r[0], "has_children": True} for r in rows]
            if node_type in {"table", "view"}:
                rows = client.query("SELECT name,type FROM system.columns WHERE database={db:String} AND table={table:String} ORDER BY position",
                                    parameters={"db": database or schema, "table": table}).result_rows
                return [{"id": f"column:{database}.{table}.{r[0]}", "name": r[0], "type": "column",
                         "data_type": r[1], "has_children": False} for r in rows]
            return []
        finally:
            client.close()
