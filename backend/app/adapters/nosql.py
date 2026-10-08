import shlex
from typing import Any

from .base import AdapterResult, DatabaseAdapter
from .relational import safe_value


class RedisAdapter(DatabaseAdapter):
    key = "redis"
    label = "Redis"
    default_port = 6379
    query_language = "Redis command"
    capabilities = ["command", "keys", "write", "export"]

    def _client(self):
        import redis
        options = self.config.get("options", {})
        return redis.Redis(host=self.config["host"], port=self.config.get("port") or 6379,
                           username=self.config.get("username") or None,
                           password=self.config.get("password") or None,
                           db=int(self.config.get("database") or 0),
                           ssl=bool(options.get("secure", False)), socket_connect_timeout=10)

    def test(self):
        client = self._client()
        return {"ok": bool(client.ping()), "version": client.info().get("redis_version", "unknown")}

    def objects(self):
        client = self._client()
        items = []
        for raw in client.scan_iter(count=200):
            key = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            value_type = client.type(raw)
            if isinstance(value_type, bytes):
                value_type = value_type.decode()
            items.append({"name": key, "type": value_type, "ttl": client.ttl(raw)})
            if len(items) >= 500:
                break
        return items

    def execute(self, query, parameters, max_rows):
        parts = shlex.split(query.strip())
        if not parts:
            raise ValueError("Redis command is empty")
        value = self._client().execute_command(*parts)
        rows = self._rows(value)[:max_rows]
        return AdapterResult(["value"], rows, len(rows), len(rows) >= max_rows)

    def overview(self):
        result = super().overview()
        info = self._client().info()
        result.update({"object_count": info.get("db0", {}).get("keys", 0),
                       "memory_used": info.get("used_memory_human"),
                       "mode": info.get("redis_mode")})
        return result

    def object_details(self, schema, name):
        client = self._client()
        value_type = self._decode(client.type(name))
        sample = None
        if value_type == "string":
            sample = self._decode(client.get(name))
        return {"schema": schema, "name": name, "type": value_type, "ttl": client.ttl(name),
                "memory_bytes": client.memory_usage(name), "sample": sample, "columns": [], "indexes": [], "ddl": ""}

    @staticmethod
    def _rows(value: Any):
        if isinstance(value, (list, tuple, set)):
            return [[RedisAdapter._decode(item)] for item in value]
        if isinstance(value, dict):
            return [[RedisAdapter._decode(k), RedisAdapter._decode(v)] for k, v in value.items()]
        return [[RedisAdapter._decode(value)]]

    @staticmethod
    def _decode(value):
        return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


class Neo4jAdapter(DatabaseAdapter):
    key = "neo4j"
    label = "Neo4j"
    default_port = 7687
    query_language = "Cypher"
    capabilities = ["query", "metadata", "graph", "write", "export"]

    def _driver(self):
        from neo4j import GraphDatabase
        scheme = self.config.get("options", {}).get("scheme", "bolt")
        uri = f"{scheme}://{self.config['host']}:{self.config.get('port') or 7687}"
        return GraphDatabase.driver(uri, auth=(self.config.get("username"), self.config.get("password")))

    def test(self):
        with self._driver() as driver:
            driver.verify_connectivity()
            info = driver.get_server_info()
            return {"ok": True, "version": info.agent}

    def objects(self):
        with self._driver() as driver:
            records, _, _ = driver.execute_query("CALL db.labels() YIELD label RETURN label ORDER BY label",
                                                  database_=self.config.get("database") or None)
            return [{"name": row["label"], "type": "label"} for row in records]

    def execute(self, query, parameters, max_rows):
        with self._driver() as driver:
            records, summary, keys = driver.execute_query(query, parameters_=parameters,
                                                          database_=self.config.get("database") or None)
            data = records[:max_rows + 1]
            rows = [[self._convert(row.get(key)) for key in keys] for row in data[:max_rows]]
            return AdapterResult(list(keys), rows, len(rows), len(data) > max_rows,
                                 summary.query_type if summary else "")

    @staticmethod
    def _convert(value):
        if hasattr(value, "data"):
            return value.data()
        if isinstance(value, list):
            return [Neo4jAdapter._convert(v) for v in value]
        if isinstance(value, dict):
            return {k: Neo4jAdapter._convert(v) for k, v in value.items()}
        return safe_value(value)


class NebulaAdapter(DatabaseAdapter):
    key = "nebula"
    label = "NebulaGraph"
    default_port = 9669
    query_language = "nGQL"
    capabilities = ["query", "metadata", "graph", "write", "export"]

    def _session(self):
        from nebula3.Config import Config
        from nebula3.gclient.net import ConnectionPool
        pool = ConnectionPool()
        config = Config()
        config.max_connection_pool_size = 5
        if not pool.init([(self.config["host"], self.config.get("port") or 9669)], config):
            raise ConnectionError("Unable to initialize NebulaGraph connection pool")
        session = pool.get_session(self.config.get("username") or "root", self.config.get("password") or "nebula")
        return pool, session

    def test(self):
        pool, session = self._session()
        try:
            result = session.execute("SHOW HOSTS")
            if not result.is_succeeded():
                raise RuntimeError(result.error_msg())
            return {"ok": True, "version": "connected"}
        finally:
            session.release(); pool.close()

    def objects(self):
        pool, session = self._session()
        try:
            result = session.execute("SHOW SPACES")
            return [{"name": str(row), "type": "space"} for row in result.rows()]
        finally:
            session.release(); pool.close()

    def execute(self, query, parameters, max_rows):
        if parameters:
            raise ValueError("NebulaGraph named parameters are not supported in this version")
        pool, session = self._session()
        try:
            result = session.execute(query)
            if not result.is_succeeded():
                raise RuntimeError(result.error_msg())
            columns = list(result.keys())
            rows = []
            for row in result.rows()[:max_rows + 1]:
                rows.append([str(v) for v in row.values])
            return AdapterResult(columns, rows[:max_rows], len(rows[:max_rows]), len(rows) > max_rows)
        finally:
            session.release(); pool.close()
