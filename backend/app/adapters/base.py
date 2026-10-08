from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class AdapterResult:
    columns: List[str]
    rows: List[List[Any]]
    row_count: int
    truncated: bool = False
    message: str = ""


class DatabaseAdapter(ABC):
    key = "base"
    label = "Base"
    default_port = None
    query_language = "SQL"
    capabilities: List[str] = ["query"]

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abstractmethod
    def test(self) -> Dict[str, Any]: ...

    @abstractmethod
    def objects(self) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def execute(self, query: str, parameters: Dict[str, Any], max_rows: int) -> AdapterResult: ...

    def import_rows(self, table: str, columns: List[str], rows: List[List[Any]]) -> int:
        raise ValueError(f"{self.label} does not support tabular import")

    def overview(self) -> Dict[str, Any]:
        status = self.test()
        return {
            **status,
            "driver": self.key,
            "label": self.label,
            "host": self.config.get("host", ""),
            "port": self.config.get("port") or self.default_port,
            "database": self.config.get("database", ""),
            "username": self.config.get("username", ""),
            "capabilities": self.capabilities,
        }

    def object_details(self, schema: str, name: str) -> Dict[str, Any]:
        return {"schema": schema, "name": name, "columns": [], "indexes": [], "ddl": ""}

    def tree(self, node_type: str = "root", database: str = "", schema: str = "", table: str = "") -> List[Dict[str, Any]]:
        if node_type == "root":
            return [{"id": "objects", "name": self.config.get("database") or self.label,
                     "type": "database", "database": self.config.get("database", ""), "has_children": True}]
        if node_type in {"database", "schema"}:
            return [{**item, "id": f"{item.get('schema', '')}.{item['name']}", "database": database,
                     "schema": item.get("schema", schema), "table": item["name"], "has_children": True}
                    for item in self.objects()]
        if node_type in {"table", "view"}:
            details = self.object_details(schema or database, table)
            return [{"id": f"{table}.{column.get('name')}", "name": str(column.get("name")),
                     "type": "column", "data_type": column.get("type", ""), "has_children": False}
                    for column in details.get("columns", [])]
        return []
