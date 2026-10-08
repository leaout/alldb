from typing import Dict, Type

from .base import DatabaseAdapter
from .clickhouse import ClickHouseAdapter
from .nosql import NebulaAdapter, Neo4jAdapter, RedisAdapter
from .relational import MySQLAdapter, PostgresAdapter, TiDBAdapter
from .sqlite import SQLiteAdapter


ADAPTERS: Dict[str, Type[DatabaseAdapter]] = {
    cls.key: cls for cls in [SQLiteAdapter, MySQLAdapter, TiDBAdapter, PostgresAdapter,
                             ClickHouseAdapter, RedisAdapter, Neo4jAdapter, NebulaAdapter]
}


def adapter_catalog():
    return [{"key": cls.key, "label": cls.label, "default_port": cls.default_port,
             "query_language": cls.query_language, "capabilities": cls.capabilities}
            for cls in ADAPTERS.values()]


def create_adapter(config):
    try:
        return ADAPTERS[config["driver"]](config)
    except KeyError as exc:
        raise ValueError(f"Unsupported database driver: {config['driver']}") from exc

