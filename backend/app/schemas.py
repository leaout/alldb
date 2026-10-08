from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class ConnectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    driver: str
    host: str = "localhost"
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    database: str = ""
    username: str = ""
    password: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)
    readonly: bool = False


class ConnectionView(BaseModel):
    id: str
    name: str
    driver: str
    host: str
    port: Optional[int]
    database: str
    username: str
    options: Dict[str, Any]
    readonly: bool
    created_at: str
    updated_at: str


class QueryRequest(BaseModel):
    connection_id: str
    query: str = Field(min_length=1)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    max_rows: int = Field(default=1000, ge=1, le=100000)


class QueryResult(BaseModel):
    columns: List[str]
    rows: List[List[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: int
    message: str = ""


class ExportRequest(QueryRequest):
    format: str = "csv"

    @model_validator(mode="after")
    def validate_format(self):
        if self.format not in {"csv", "json"}:
            raise ValueError("format must be csv or json")
        return self

