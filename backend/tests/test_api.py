import sqlite3
import base64

from fastapi.testclient import TestClient

from app.main import create_app


def make_client(tmp_path):
    return TestClient(create_app(tmp_path / "platform"))


def create_sqlite_connection(client, db_path, readonly=False):
    response = client.post("/api/connections", json={
        "name": "Local demo", "driver": "sqlite", "database": str(db_path),
        "host": "localhost", "username": "", "password": "secret", "readonly": readonly,
    })
    assert response.status_code == 201
    assert "password" not in response.json()
    return response.json()["id"]


def test_health_and_driver_catalog(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/api/health").json()["status"] == "ok"
    keys = {item["key"] for item in client.get("/api/drivers").json()}
    assert {"mysql", "postgresql", "tidb", "clickhouse", "redis", "neo4j", "nebula", "sqlite"} <= keys


def test_connection_query_objects_and_export(tmp_path):
    db_path = tmp_path / "demo.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT)")
        db.executemany("INSERT INTO people(name) VALUES (?)", [("峰哥",), ("Alice",)])

    client = make_client(tmp_path)
    connection_id = create_sqlite_connection(client, db_path)
    assert client.post(f"/api/connections/{connection_id}/test").json()["ok"] is True
    objects = client.get(f"/api/connections/{connection_id}/objects").json()
    assert any(item["name"] == "people" for item in objects)
    overview = client.get(f"/api/connections/{connection_id}/overview").json()
    assert overview["driver"] == "sqlite"
    assert overview["object_count"] == 1
    details = client.get(f"/api/connections/{connection_id}/object-details", params={"name": "people"}).json()
    assert [column["name"] for column in details["columns"]] == ["id", "name"]
    roots = client.get(f"/api/connections/{connection_id}/tree").json()
    assert roots[0]["name"] == "main"
    tables = client.get(f"/api/connections/{connection_id}/tree", params={"node_type": "database", "database": "main"}).json()
    assert tables[0]["name"] == "people"
    columns = client.get(f"/api/connections/{connection_id}/tree", params={"node_type": "table", "database": "main", "table": "people"}).json()
    assert [column["name"] for column in columns] == ["id", "name"]

    result = client.post("/api/query", json={
        "connection_id": connection_id, "query": "SELECT id,name FROM people ORDER BY id", "max_rows": 1
    }).json()
    assert result["columns"] == ["id", "name"]
    assert result["rows"] == [[1, "峰哥"]]
    assert result["truncated"] is True

    export = client.post("/api/export", json={
        "connection_id": connection_id, "query": "SELECT name FROM people ORDER BY id",
        "format": "csv", "max_rows": 10
    })
    assert export.status_code == 200
    assert "峰哥" in export.content.decode("utf-8-sig")


def test_readonly_blocks_writes_and_password_is_preserved(tmp_path):
    client = make_client(tmp_path)
    connection_id = create_sqlite_connection(client, tmp_path / "readonly.sqlite3", readonly=True)
    blocked = client.post("/api/query", json={
        "connection_id": connection_id, "query": "CREATE TABLE nope(id int)"
    })
    assert blocked.status_code == 403

    current = client.get("/api/connections").json()[0]
    current["password"] = None
    updated = client.put(f"/api/connections/{connection_id}", json=current)
    assert updated.status_code == 200
    assert "password" not in updated.json()


def test_delete_connection(tmp_path):
    client = make_client(tmp_path)
    connection_id = create_sqlite_connection(client, tmp_path / "delete.sqlite3")
    assert client.delete(f"/api/connections/{connection_id}").status_code == 204
    assert client.get("/api/connections").json() == []


def test_csv_import(tmp_path):
    db_path = tmp_path / "import.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE people (id INTEGER, name TEXT)")
    client = make_client(tmp_path)
    connection_id = create_sqlite_connection(client, db_path)
    response = client.post("/api/import", data={"connection_id": connection_id, "table": "people"},
                           files={"file": ("people.csv", "id,name\n1,Alice\n2,峰哥\n", "text/csv")})
    assert response.status_code == 200
    assert response.json()["imported"] == 2
    result = client.post("/api/query", json={"connection_id": connection_id,
                                             "query": "SELECT name FROM people ORDER BY id"})
    assert result.json()["rows"] == [["Alice"], ["峰哥"]]


def test_basic_auth_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLDB_ADMIN_USER", "admin")
    monkeypatch.setenv("ALLDB_ADMIN_PASSWORD", "test-password")
    client = make_client(tmp_path)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/drivers").status_code == 401
    token = base64.b64encode(b"admin:test-password").decode()
    assert client.get("/api/drivers", headers={"Authorization": f"Basic {token}"}).status_code == 200


def test_unsaved_connection_can_be_tested(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/api/connections/test", json={
        "name": "Before save", "driver": "sqlite", "database": str(tmp_path / "new.sqlite3")
    })
    assert response.status_code == 200
    assert response.json()["ok"] is True
