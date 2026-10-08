import base64
import csv
import hmac
import io
import json
import os
import time
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .adapters import ADAPTERS, adapter_catalog, create_adapter
from .config import get_settings
from .crypto import SecretBox
from .schemas import ConnectionInput, ConnectionView, ExportRequest, QueryRequest, QueryResult
from .store import ConnectionStore


def create_app(data_dir=None):
    settings = get_settings()
    root = Path(data_dir).resolve() if data_dir else settings.data_dir
    root.mkdir(parents=True, exist_ok=True)
    store = ConnectionStore(root / "alldb.sqlite3", SecretBox(settings.secret))
    app = FastAPI(title="AllDB", version="0.1.0")
    app.state.store = store
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                       allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def basic_auth(request, call_next):
        desktop_token = os.getenv("ALLDB_DESKTOP_TOKEN", "")
        if desktop_token and request.url.path != "/api/health":
            supplied = request.headers.get("X-AllDB-Token", "")
            if not hmac.compare_digest(supplied, desktop_token):
                return Response(status_code=401)
            return await call_next(request)
        if not settings.admin_password or request.url.path == "/api/health":
            return await call_next(request)
        try:
            scheme, encoded = request.headers.get("Authorization", "").split(" ", 1)
            username, password = base64.b64decode(encoded).decode("utf-8").split(":", 1)
            valid = (scheme.lower() == "basic"
                     and hmac.compare_digest(username, settings.admin_user)
                     and hmac.compare_digest(password, settings.admin_password))
        except (ValueError, UnicodeDecodeError):
            valid = False
        if not valid:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="AllDB"'})
        return await call_next(request)

    def config_or_404(connection_id):
        value = store.get(connection_id, include_password=True)
        if not value:
            raise HTTPException(404, "Connection not found")
        return value

    def guard_readonly(config, query):
        if not config.get("readonly"):
            return
        first = query.lstrip().split(None, 1)[0].upper() if query.strip() else ""
        allowed = {"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "WITH", "MATCH", "RETURN", "CALL", "SCAN", "GET", "HGETALL", "SMEMBERS", "ZRANGE", "LRANGE"}
        if first not in allowed:
            raise HTTPException(403, "This connection is read-only")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": app.version}

    @app.get("/api/drivers")
    def drivers():
        return adapter_catalog()

    @app.get("/api/connections", response_model=List[ConnectionView])
    def list_connections():
        return store.list()

    @app.post("/api/connections", response_model=ConnectionView, status_code=201)
    def create_connection(value: ConnectionInput):
        if value.driver not in ADAPTERS:
            raise HTTPException(400, "Unsupported database driver")
        return store.create(value)

    @app.post("/api/connections/test")
    def test_unsaved_connection(value: ConnectionInput, existing_id: str = ""):
        if value.driver not in ADAPTERS:
            raise HTTPException(400, "Unsupported database driver")
        try:
            config = value.model_dump()
            if existing_id and value.password is None:
                current = config_or_404(existing_id)
                config["password"] = current.get("password", "")
            return create_adapter(config).test()
        except Exception as exc:
            raise HTTPException(400, f"Connection failed: {exc}") from exc

    @app.put("/api/connections/{connection_id}", response_model=ConnectionView)
    def update_connection(connection_id: str, value: ConnectionInput):
        if value.driver not in ADAPTERS:
            raise HTTPException(400, "Unsupported database driver")
        result = store.update(connection_id, value)
        if not result:
            raise HTTPException(404, "Connection not found")
        return result

    @app.delete("/api/connections/{connection_id}", status_code=204)
    def delete_connection(connection_id: str):
        if not store.delete(connection_id):
            raise HTTPException(404, "Connection not found")
        return Response(status_code=204)

    @app.post("/api/connections/{connection_id}/test")
    def test_connection(connection_id: str):
        try:
            return create_adapter(config_or_404(connection_id)).test()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, f"Connection failed: {exc}") from exc

    @app.get("/api/connections/{connection_id}/objects")
    def connection_objects(connection_id: str):
        try:
            return create_adapter(config_or_404(connection_id)).objects()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, f"Unable to load objects: {exc}") from exc

    @app.get("/api/connections/{connection_id}/overview")
    def connection_overview(connection_id: str):
        try:
            return create_adapter(config_or_404(connection_id)).overview()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, f"Unable to load connection information: {exc}") from exc

    @app.get("/api/connections/{connection_id}/object-details")
    def object_details(connection_id: str, name: str, schema: str = ""):
        try:
            return create_adapter(config_or_404(connection_id)).object_details(schema, name)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, f"Unable to load object details: {exc}") from exc

    @app.get("/api/connections/{connection_id}/tree")
    def connection_tree(connection_id: str, node_type: str = "root", database: str = "",
                        schema: str = "", table: str = ""):
        try:
            return create_adapter(config_or_404(connection_id)).tree(node_type, database, schema, table)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, f"Unable to load database tree: {exc}") from exc

    def run_query(request: QueryRequest):
        config = config_or_404(request.connection_id)
        guard_readonly(config, request.query)
        started = time.perf_counter()
        result = create_adapter(config).execute(request.query, request.parameters,
                                                min(request.max_rows, settings.max_rows))
        return result, int((time.perf_counter() - started) * 1000)

    @app.post("/api/query", response_model=QueryResult)
    def query(request: QueryRequest):
        try:
            result, elapsed = run_query(request)
            return QueryResult(columns=result.columns, rows=result.rows, row_count=result.row_count,
                               truncated=result.truncated, elapsed_ms=elapsed, message=result.message)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, f"Query failed: {exc}") from exc

    @app.post("/api/export")
    def export(request: ExportRequest):
        try:
            result, _ = run_query(request)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, f"Export failed: {exc}") from exc
        buffer = io.StringIO()
        if request.format == "csv":
            writer = csv.writer(buffer)
            writer.writerow(result.columns)
            writer.writerows(result.rows)
            media, suffix = "text/csv", "csv"
        else:
            json.dump([dict(zip(result.columns, row)) for row in result.rows], buffer,
                      ensure_ascii=False, default=str)
            media, suffix = "application/json", "json"
        payload = buffer.getvalue().encode("utf-8-sig" if request.format == "csv" else "utf-8")
        return StreamingResponse(iter([payload]), media_type=media,
                                 headers={"Content-Disposition": f'attachment; filename="export.{suffix}"'})

    @app.post("/api/import")
    async def import_data(connection_id: str = Form(...), table: str = Form(...),
                          file: UploadFile = File(...)):
        config = config_or_404(connection_id)
        if config.get("readonly"):
            raise HTTPException(403, "This connection is read-only")
        content = await file.read(20 * 1024 * 1024 + 1)
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(413, "Import file exceeds the 20 MB limit")
        try:
            text = content.decode("utf-8-sig")
            if (file.filename or "").lower().endswith(".json"):
                values = json.loads(text)
                if not isinstance(values, list) or not values or not all(isinstance(row, dict) for row in values):
                    raise ValueError("JSON must be a non-empty array of objects")
                columns = list(values[0].keys())
                if any(set(row.keys()) != set(columns) for row in values):
                    raise ValueError("All JSON objects must have the same fields")
                rows = [[row.get(column) for column in columns] for row in values]
            else:
                reader = csv.reader(io.StringIO(text))
                columns = next(reader, [])
                rows = list(reader)
                if not columns:
                    raise ValueError("CSV header is required")
                if any(len(row) != len(columns) for row in rows):
                    raise ValueError("CSV rows do not match the header column count")
            if len(rows) > 100000:
                raise ValueError("Import is limited to 100,000 rows per file")
            imported = create_adapter(config).import_rows(table, columns, rows)
            return {"imported": imported, "table": table, "columns": columns}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, f"Import failed: {exc}") from exc

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        assets = static_dir / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            candidate = static_dir / path
            if path and candidate.is_file() and static_dir in candidate.resolve().parents:
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")
    return app


app = create_app()
