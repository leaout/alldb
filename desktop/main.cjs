const { app, BrowserWindow, Menu, dialog, session } = require('electron')
const { spawn } = require('node:child_process')
const crypto = require('node:crypto')
const fs = require('node:fs')
const http = require('node:http')
const net = require('node:net')
const path = require('node:path')

let mainWindow = null
let coreProcess = null
let quitting = false

function reservePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.on('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port
      server.close(() => resolve(port))
    })
  })
}

function coreCommand(port, token) {
  const projectRoot = path.resolve(__dirname, '..')
  const env = { ...process.env, ALLDB_DESKTOP_TOKEN: token, PYTHONUNBUFFERED: '1' }
  if (app.isPackaged) {
    return {
      command: path.join(process.resourcesPath, 'sidecar', 'AllDB-Core.exe'),
      args: ['--port', String(port)], env, cwd: process.resourcesPath,
    }
  }
  const venvPython = path.join(projectRoot, '.venv-win-build', 'Scripts', 'python.exe')
  const python = process.env.ALLDB_PYTHON || (fs.existsSync(venvPython) ? venvPython : 'python')
  env.PYTHONPATH = path.join(projectRoot, 'backend')
  return {
    command: python,
    args: [path.join(projectRoot, 'backend', 'sidecar.py'), '--port', String(port)], env, cwd: projectRoot,
  }
}

function startCore(port, token) {
  const spec = coreCommand(port, token)
  const logs = app.getPath('logs')
  fs.mkdirSync(logs, { recursive: true })
  const stream = fs.createWriteStream(path.join(logs, 'core.log'), { flags: 'a' })
  coreProcess = spawn(spec.command, spec.args, {
    cwd: spec.cwd, env: spec.env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  })
  coreProcess.stdout.pipe(stream)
  coreProcess.stderr.pipe(stream)
  coreProcess.on('exit', (code) => {
    if (!quitting && mainWindow) {
      dialog.showErrorBox('AllDB 核心服务已停止', `数据库服务异常退出，代码：${code}`)
      app.quit()
    }
  })
}

function waitForCore(port, timeoutMs = 60000) {
  const started = Date.now()
  return new Promise((resolve, reject) => {
    const probe = () => {
      const request = http.get(`http://127.0.0.1:${port}/api/health`, { timeout: 800 }, (response) => {
        response.resume()
        if (response.statusCode === 200) resolve()
        else retry()
      })
      request.on('timeout', () => request.destroy())
      request.on('error', retry)
    }
    const retry = () => {
      if (Date.now() - started >= timeoutMs) reject(new Error('核心服务启动超时'))
      else setTimeout(probe, 180)
    }
    probe()
  })
}

async function createWindow() {
  const port = await reservePort()
  const token = crypto.randomBytes(32).toString('hex')
  const baseUrl = `http://127.0.0.1:${port}`

  session.defaultSession.webRequest.onBeforeSendHeaders(
    { urls: [`${baseUrl}/*`] },
    (details, callback) => callback({ requestHeaders: { ...details.requestHeaders, 'X-AllDB-Token': token } }),
  )

  mainWindow = new BrowserWindow({
    title: 'AllDB 数据库工作台', width: 1440, height: 900, minWidth: 1050, minHeight: 680,
    show: false, backgroundColor: '#0d1119', autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true },
  })
  Menu.setApplicationMenu(null)
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(baseUrl)) event.preventDefault()
  })
  mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent('<body style="margin:0;background:#0d1119;color:#b8c1d0;font:16px Segoe UI;display:grid;place-items:center;height:100vh"><div><b style="font-size:30px;color:#8e86ff">AllDB</b><p>正在启动数据库工作台…</p></div></body>')}`)
  mainWindow.once('ready-to-show', () => mainWindow.show())

  startCore(port, token)
  await waitForCore(port)
  await mainWindow.loadURL(baseUrl)
}

const lock = app.requestSingleInstanceLock()
if (!lock) app.quit()
else {
  app.on('second-instance', () => {
    if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus() }
  })
  app.whenReady().then(createWindow).catch((error) => {
    dialog.showErrorBox('AllDB 启动失败', error.stack || String(error))
    app.quit()
  })
  app.on('window-all-closed', () => app.quit())
  app.on('before-quit', () => {
    quitting = true
    if (coreProcess && !coreProcess.killed) coreProcess.kill()
  })
}

