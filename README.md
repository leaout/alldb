# AllDB

AllDB 是一个部署在 Linux 上、通过浏览器使用的多数据库工作台。当前版本提供连接管理、对象浏览、查询或命令执行、结果表格、只读保护以及 CSV/JSON 导出。

已接入的适配器：

- MySQL / MariaDB
- PostgreSQL
- TiDB
- ClickHouse
- Redis
- Neo4j
- NebulaGraph
- SQLite

## 使用 Docker Compose 启动

要求 Linux 或 WSL2 已安装 Docker 及 Compose 插件。

```bash
cp .env.example .env
openssl rand -hex 32
# 将输出填入 .env 的 ALLDB_SECRET
docker compose up --build -d
```

打开 `http://localhost:8080`，浏览器会要求输入 `.env` 中的管理员账号和密码。数据库运行在宿主机时，连接地址填写 `host.docker.internal`；连接其他容器时，将 AllDB 与目标容器加入同一 Docker 网络并使用服务名。

停止服务：

```bash
docker compose down
```

平台数据保存在 `alldb-data` Docker volume。请妥善保存 `ALLDB_SECRET`；更换它之后，已有连接密码将无法解密。

## WSL 开发与测试

后端：

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

前端可以直接通过 Docker 构建，也可以安装 Node.js 22 后运行：

```bash
cd frontend
npm install
npm run dev
```

开发模式下前端将 `/api` 转发至 `http://localhost:8000`。

## Windows 一体化桌面程序

Windows 版本采用 Electron 内置 Chromium，并捆绑 Python 核心服务和所有数据库驱动。目标电脑不需要安装浏览器、Python、Node.js 或 WSL。

在安装了 Python 3.11 和 Node.js 的 Windows 构建机上执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\windows\build.ps1 -Clean
```

输出文件为 `dist-windows\AllDB-Portable-0.1.0-x64.exe`。这是单文件便携程序，双击即可运行。Electron 主进程会启动内置 `AllDB-Core.exe`，使用随机回环端口和一次性令牌通信，然后在应用窗口中加载数据库工作台。程序不会打开系统浏览器，也不会监听局域网地址。

用户数据位于 `%LOCALAPPDATA%\AllDB`。连接密码的主密钥通过 Windows DPAPI 加密，因此只能由同一个 Windows 用户解密。升级或替换便携 EXE 不会删除连接配置。

开发调试桌面外壳：

```powershell
cd desktop
npm ci
npm start
```

## API

服务启动后可访问 `/docs` 查看 OpenAPI 文档。核心接口包括：

- `GET /api/drivers`
- `GET/POST /api/connections`
- `POST /api/connections/{id}/test`
- `GET /api/connections/{id}/objects`
- `POST /api/query`
- `POST /api/export`
- `POST /api/import`（CSV/JSON，单文件最大 20 MB、100,000 行）

连接密码使用由 `ALLDB_SECRET` 派生的 Fernet 密钥加密，API 不会回传密码。容器部署默认启用 HTTP Basic 身份认证；公网环境仍应通过 Nginx、Caddy 或企业网关提供 HTTPS。

## 当前边界

这是首个可运行版本。大规模导出目前仍在 API 进程中完成；细粒度多用户权限、审计日志、SSH 隧道、后台任务队列、查询取消、跨库迁移和图形化节点视图属于下一阶段。
