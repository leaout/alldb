"""AllDB desktop sidecar served on a private loopback port."""

import argparse
import base64
import os
import secrets
from pathlib import Path


APP_NAME = "AllDB"


def data_directory() -> Path:
    configured = os.getenv("ALLDB_DATA_DIR")
    if configured:
        result = Path(configured)
    else:
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        result = base / APP_NAME
    result.mkdir(parents=True, exist_ok=True)
    return result


def load_master_secret(root: Path) -> str:
    """Load a DPAPI-protected key, creating it on first desktop launch."""
    secret_file = root / "master-key.dpapi"
    try:
        import win32crypt

        if secret_file.exists():
            encrypted = base64.b64decode(secret_file.read_bytes())
            return win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1].decode("ascii")
        value = secrets.token_hex(32)
        encrypted = win32crypt.CryptProtectData(value.encode("ascii"), APP_NAME, None, None, None, 0)
        secret_file.write_bytes(base64.b64encode(encrypted))
        return value
    except ImportError:
        fallback = root / ".development-secret"
        if fallback.exists():
            return fallback.read_text(encoding="utf-8").strip()
        value = secrets.token_hex(32)
        fallback.write_text(value, encoding="utf-8")
        return value


def configure_environment() -> Path:
    root = data_directory()
    os.environ["ALLDB_DATA_DIR"] = str(root)
    os.environ["ALLDB_SECRET"] = load_master_secret(root)
    os.environ.setdefault("ALLDB_MAX_ROWS", "5000")
    os.environ.pop("ALLDB_ADMIN_USER", None)
    os.environ.pop("ALLDB_ADMIN_PASSWORD", None)
    return root


def main() -> int:
    parser = argparse.ArgumentParser(description="AllDB desktop application server")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    configure_environment()

    import uvicorn
    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
