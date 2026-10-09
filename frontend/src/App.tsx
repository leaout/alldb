import { useEffect, useMemo, useRef, useState } from 'react'
import Editor from '@monaco-editor/react'
import { Braces, CheckCircle2, ChevronDown, ChevronRight, Database, Download, Info, KeyRound, Pencil, Play, Plus, RefreshCw, Search, Server, Settings2, Table2, Trash2, Upload, X } from 'lucide-react'
import { api } from './api'
import type { Connection, ConnectionOverview, DbObject, Driver, ObjectDetails, QueryResult, TreeNode } from './types'

const defaults: Record<string, string> = {
  sqlite: 'SELECT name, type FROM sqlite_master ORDER BY type, name;',
  redis: 'INFO', neo4j: 'MATCH (n) RETURN n LIMIT 25', nebula: 'SHOW SPACES',
  clickhouse: 'SELECT version(), now()', postgresql: 'SELECT version();',
  mysql: 'SELECT VERSION();', tidb: 'SELECT VERSION();',
}

type FormValue = { name: string; driver: string; host: string; port: string; database: string; username: string; password: string; readonly: boolean }
const emptyForm: FormValue = { name: '', driver: 'mysql', host: 'localhost', port: '3306', database: '', username: '', password: '', readonly: false }
type QueryTab = { id: string; title: string; query: string; result: QueryResult | null; message: string; failed: boolean; resultPanel: 'results' | 'messages' }

function makeQueryTab(number: number, query = 'SELECT 1;'): QueryTab {
  return { id: `query-${number}`, title: `查询 ${number}`, query, result: null, message: '运行查询后，结果会显示在这里', failed: false, resultPanel: 'results' }
}

function displayCell(value: unknown) {
  if (value === null) return <span className="null">NULL</span>
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function InfoCard({ label, value }: { label: string; value: unknown }) {
  return <div className="info-card"><span>{label}</span><strong>{value === null || value === undefined || value === '' ? '-' : String(value)}</strong></div>
}

function MetadataTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows.length) return <div className="metadata-empty">暂无信息</div>
  const columns = [...new Set(rows.flatMap(row => Object.keys(row)))]
  return <div className="metadata-table-wrap"><table><thead><tr>{columns.map(column => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map(column => <td key={column}>{displayCell(row[column])}</td>)}</tr>)}</tbody></table></div>
}

export default function App() {
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [connections, setConnections] = useState<Connection[]>([])
  const [activeId, setActiveId] = useState('')
  const [objects, setObjects] = useState<DbObject[]>([])
  const [treeRoots, setTreeRoots] = useState<TreeNode[]>([])
  const [treeChildren, setTreeChildren] = useState<Record<string, TreeNode[]>>({})
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set())
  const [loadingNodes, setLoadingNodes] = useState<Set<string>>(new Set())
  const [queryTabs, setQueryTabs] = useState<QueryTab[]>([makeQueryTab(1)])
  const [activeQueryId, setActiveQueryId] = useState('query-1')
  const [nextQueryNumber, setNextQueryNumber] = useState(2)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('就绪')
  const [search, setSearch] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<FormValue>(emptyForm)
  const [editingId, setEditingId] = useState('')
  const [formTesting, setFormTesting] = useState(false)
  const [formTestResult, setFormTestResult] = useState('')
  const [overview, setOverview] = useState<ConnectionOverview | null>(null)
  const [overviewLoading, setOverviewLoading] = useState(false)
  const [overviewError, setOverviewError] = useState('')
  const [objectError, setObjectError] = useState('')
  const [details, setDetails] = useState<ObjectDetails | null>(null)
  const [view, setView] = useState<'overview' | 'query' | 'details'>('overview')
  const importInput = useRef<HTMLInputElement>(null)

  const active = connections.find(item => item.id === activeId)
  const activeQuery = queryTabs.find(item => item.id === activeQueryId) || queryTabs[0]
  const query = activeQuery?.query || ''
  const result = activeQuery?.result || null
  const language = active?.driver === 'neo4j' ? 'cypher' : active?.driver === 'redis' ? 'shell' : 'sql'
  const allTreeNodes = useMemo(() => [...treeRoots, ...Object.values(treeChildren).flat()], [treeRoots, treeChildren])

  function updateQueryTab(id: string, update: Partial<QueryTab>) {
    setQueryTabs(current => current.map(tab => tab.id === id ? { ...tab, ...update } : tab))
  }

  function openQueryTab() {
    const number = nextQueryNumber
    setNextQueryNumber(number + 1)
    setQueryTabs(current => [...current, makeQueryTab(number, active ? defaults[active.driver] || 'SELECT 1;' : 'SELECT 1;')])
    setActiveQueryId(`query-${number}`)
    setView('query')
  }

  function closeQueryTab(id: string) {
    if (queryTabs.length === 1) {
      const number = nextQueryNumber
      setNextQueryNumber(number + 1)
      setQueryTabs([makeQueryTab(number, active ? defaults[active.driver] || 'SELECT 1;' : 'SELECT 1;')])
      setActiveQueryId(`query-${number}`)
      setView('query')
      return
    }
    const index = queryTabs.findIndex(tab => tab.id === id)
    const remaining = queryTabs.filter(tab => tab.id !== id)
    setQueryTabs(remaining)
    if (activeQueryId === id) setActiveQueryId(remaining[Math.max(0, index - 1)].id)
  }

  async function loadConnections() {
    const values = await api.connections()
    setConnections(values)
    if (!activeId && values.length) setActiveId(values[0].id)
  }

  useEffect(() => { Promise.all([api.drivers(), api.connections()]).then(([d, c]) => { setDrivers(d); setConnections(c); if (c.length) setActiveId(c[0].id) }).catch(e => setNotice(e.message)) }, [])
  useEffect(() => {
    if (!activeId) { setObjects([]); setOverview(null); return }
    const connection = connections.find(c => c.id === activeId)
    if (connection && activeQuery) updateQueryTab(activeQuery.id, { query: defaults[connection.driver] || 'SELECT 1;', result: null, message: '运行查询后，结果会显示在这里', failed: false, resultPanel: 'results' })
    setDetails(null); setView('overview')
    refreshObjects(); loadOverview()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId])

  async function refreshObjects() {
    if (!activeId) return
    setObjectError('')
    try {
      const roots = await api.tree(activeId)
      setTreeRoots(roots); setTreeChildren({}); setExpandedNodes(new Set()); setObjects([])
      setNotice(`已发现 ${roots.length} 个数据库`)
    } catch (e) { const message = (e as Error).message; setTreeRoots([]); setTreeChildren({}); setObjectError(message); setNotice(message) }
  }

  async function toggleTreeNode(node: TreeNode) {
    if (!node.has_children) return
    if (expandedNodes.has(node.id)) {
      setExpandedNodes(current => { const next = new Set(current); next.delete(node.id); return next })
      return
    }
    setExpandedNodes(current => new Set(current).add(node.id))
    if (treeChildren[node.id]) return
    setLoadingNodes(current => new Set(current).add(node.id))
    try {
      const children = await api.tree(activeId, node)
      setTreeChildren(current => ({ ...current, [node.id]: children }))
      if (children.some(item => item.type === 'table' || item.type === 'view')) {
        setObjects(current => [...current, ...children.map(item => ({ name: item.name, type: item.type, schema: item.schema }))])
      }
      setNotice(`${node.name} · ${children.length} 个对象`)
    } catch (e) { const message = (e as Error).message; setNotice(message); setTreeChildren(current => ({ ...current, [node.id]: [] })) }
    finally { setLoadingNodes(current => { const next = new Set(current); next.delete(node.id); return next }) }
  }

  async function loadOverview() {
    if (!activeId) return
    setOverviewLoading(true); setOverviewError('')
    try { setOverview(await api.overview(activeId)); setNotice('连接信息已加载') }
    catch (e) { const message = (e as Error).message; setOverview(null); setOverviewError(message); setNotice(message) }
    finally { setOverviewLoading(false) }
  }

  async function openObject(item: DbObject | TreeNode) {
    if (!activeId) return
    setBusy(true); setNotice(`正在读取 ${item.name}…`)
    try { setDetails(await api.objectDetails(activeId, item.name, item.schema || '')); setView('details'); setNotice(`${item.name} 元数据已加载`) }
    catch (e) { setNotice((e as Error).message) }
    finally { setBusy(false) }
  }

  function queryObject(item: DbObject | TreeNode) {
    const scope = item.schema || ('database' in item ? item.database : '')
    if (activeQuery) updateQueryTab(activeQuery.id, { query: `SELECT * FROM ${scope ? `${scope}.` : ''}${item.name} LIMIT 100;`, result: null, message: '运行查询后，结果会显示在这里', failed: false, resultPanel: 'results' })
    setView('query')
  }

  async function execute() {
    if (!activeId || !activeQuery || !query.trim()) return
    const queryId = activeQuery.id
    setBusy(true); setNotice('正在执行…')
    updateQueryTab(queryId, { message: '正在执行…', failed: false, resultPanel: 'messages' })
    try {
      const value = await api.query(activeId, query)
      const message = value.message || `执行成功 · ${value.elapsed_ms} ms · ${value.row_count} 行`
      updateQueryTab(queryId, { result: value, message, failed: false, resultPanel: 'results' })
      setNotice(`完成 · ${value.elapsed_ms} ms · ${value.row_count} 行`)
    } catch (e) {
      const message = (e as Error).message || 'SQL 执行失败，数据库没有返回错误详情。'
      updateQueryTab(queryId, { result: null, message, failed: true, resultPanel: 'messages' })
      setNotice(message)
    } finally { setBusy(false) }
  }

  async function saveConnection(event: React.FormEvent) {
    event.preventDefault()
    try {
      const value = { ...form, password: editingId && !form.password ? null : form.password, port: form.port ? Number(form.port) : null, options: {} }
      const saved = editingId ? await api.updateConnection(editingId, value) : await api.createConnection(value)
      await loadConnections(); setActiveId(saved.id); setShowForm(false); setForm(emptyForm); setEditingId(''); setNotice('连接已保存')
    } catch (e) { setNotice((e as Error).message) }
  }

  async function removeConnection(id: string) {
    if (!confirm('删除这个连接配置？数据库本身不会受到影响。')) return
    try { await api.deleteConnection(id); setActiveId(''); await loadConnections(); setNotice('连接已删除') }
    catch (e) { setNotice((e as Error).message) }
  }

  async function testConnection() {
    if (!activeId) return
    setBusy(true)
    try { const value = await api.testConnection(activeId); setNotice(`连接成功 · ${value.version}`) }
    catch (e) { setNotice((e as Error).message) }
    finally { setBusy(false) }
  }

  async function testFormConnection() {
    setFormTesting(true); setFormTestResult('正在连接…')
    try {
      const value = await api.testUnsavedConnection({ ...form, name: form.name || 'Connection test', password: editingId && !form.password ? null : form.password, port: form.port ? Number(form.port) : null, options: {} }, editingId)
      setFormTestResult(`连接成功 · ${value.version}`)
    } catch (e) { setFormTestResult((e as Error).message) }
    finally { setFormTesting(false) }
  }

  async function exportData(format: 'csv' | 'json') {
    if (!activeId) return
    try {
      const response = await fetch(api.exportUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ connection_id: activeId, query, max_rows: 5000, format }) })
      if (!response.ok) throw new Error((await response.json()).detail || '导出失败')
      const url = URL.createObjectURL(await response.blob()); const anchor = document.createElement('a')
      anchor.href = url; anchor.download = `export.${format}`; anchor.click(); URL.revokeObjectURL(url)
      setNotice(`${format.toUpperCase()} 已导出`)
    } catch (e) { setNotice((e as Error).message) }
  }

  async function importData(file?: File) {
    if (!file || !activeId) return
    const suggested = objects.find(item => item.type.toLowerCase().includes('table'))?.name || ''
    const table = prompt('导入到哪个表？CSV 第一行或 JSON 对象字段将作为列名。', suggested)
    if (!table) { if (importInput.current) importInput.current.value = ''; return }
    setBusy(true); setNotice('正在导入…')
    try { const value = await api.importData(activeId, table, file); setNotice(`已向 ${value.table} 导入 ${value.imported} 行`) }
    catch (e) { setNotice((e as Error).message) }
    finally { setBusy(false); if (importInput.current) importInput.current.value = '' }
  }

  function chooseDriver(key: string) {
    const driver = drivers.find(d => d.key === key)
    setForm(v => ({ ...v, driver: key, port: driver?.default_port?.toString() || '', database: key === 'redis' ? '0' : '' }))
  }

  function openNewConnection() {
    setEditingId(''); setForm(emptyForm); setFormTestResult(''); setShowForm(true)
  }

  function openEditConnection() {
    if (!active) return
    setEditingId(active.id)
    setForm({ name: active.name, driver: active.driver, host: active.host, port: active.port?.toString() || '', database: active.database, username: active.username, password: '', readonly: active.readonly })
    setFormTestResult(''); setShowForm(true)
  }

  function treeNodeVisible(node: TreeNode): boolean {
    if (!search) return true
    const term = search.toLowerCase()
    if (`${node.name} ${node.data_type || ''}`.toLowerCase().includes(term)) return true
    return (treeChildren[node.id] || []).some(treeNodeVisible)
  }

  function renderTreeNode(node: TreeNode, depth = 0) {
    if (!treeNodeVisible(node)) return null
    const expanded = expandedNodes.has(node.id)
    const loading = loadingNodes.has(node.id)
    const isTable = node.type === 'table' || node.type === 'view'
    const icon = node.type === 'database' ? <Database size={14}/> : node.type === 'schema' ? <Braces size={14}/> : isTable ? <Table2 size={14}/> : <KeyRound size={13}/>
    return <div className="tree-branch" key={node.id}>
      <button className={`tree-node type-${node.type} ${details?.name === node.name && isTable ? 'selected' : ''}`} style={{ paddingLeft: 6 + depth * 16 }} onClick={() => { if (isTable) openObject(node); toggleTreeNode(node) }} onDoubleClick={() => { if (isTable) queryObject(node) }}>
        <span className={`tree-toggle ${loading ? 'loading' : ''}`}>{node.has_children ? expanded ? <ChevronDown size={13}/> : <ChevronRight size={13}/> : null}</span>{icon}<span className="tree-label">{node.name}</span>{node.data_type && <small>{node.data_type}</small>}
      </button>
      {expanded && <div>{loading ? <div className="tree-loading" style={{ paddingLeft: 36 + depth * 16 }}>正在读取…</div> : (treeChildren[node.id] || []).length ? (treeChildren[node.id] || []).map(child => renderTreeNode(child, depth + 1)) : <div className="tree-loading" style={{ paddingLeft: 36 + depth * 16 }}>空</div>}</div>}
    </div>
  }

  return <div className="app-shell">
    <header>
      <div className="brand"><div className="brand-icon"><Database size={22}/></div><div><strong>AllDB</strong><span>数据库工作台</span></div></div>
      <div className="header-actions"><span className="environment">LINUX WEB</span><button className="ghost"><Settings2 size={17}/></button></div>
    </header>

    <aside className="connections-panel">
      <div className="panel-title"><span>连接</span><button className="icon-button accent" onClick={openNewConnection} title="新建连接"><Plus size={16}/></button></div>
      <div className="connection-list">
        {connections.map(item => <button key={item.id} className={`connection-item ${activeId === item.id ? 'active' : ''}`} onClick={() => setActiveId(item.id)}>
          <span className={`db-dot ${item.driver}`}></span><span className="connection-copy"><strong>{item.name}</strong><small>{item.driver} · {item.host}</small></span><ChevronRight size={15}/>
        </button>)}
        {!connections.length && <div className="empty-small"><Server size={28}/><span>还没有数据库连接</span><button onClick={openNewConnection}>创建第一个连接</button></div>}
      </div>
      {active && <div className="connection-actions"><button onClick={testConnection}><RefreshCw size={14}/>测试</button><button onClick={openEditConnection}><Pencil size={14}/>编辑</button><button className="danger" onClick={() => removeConnection(active.id)}><Trash2 size={14}/></button></div>}
    </aside>

    <aside className="objects-panel">
      <div className="object-heading"><div><span>数据库对象</span>{active && <small>{active.database || active.name}</small>}</div><button className="icon-button" onClick={refreshObjects}><RefreshCw size={15}/></button></div>
      <label className="search"><Search size={15}/><input value={search} onChange={e => setSearch(e.target.value)} placeholder="筛选对象"/></label>
      <div className="object-list">
        {treeRoots.map(node => renderTreeNode(node))}
        {active && !treeRoots.length && <div className={`empty-small ${objectError ? 'load-error' : ''}`}><Braces size={25}/><span>{objectError || '没有可显示的数据库'}</span>{objectError && <button onClick={refreshObjects}>重新加载</button>}</div>}
      </div>
    </aside>

    <main>
      <div className="tabbar">
        {active && <button className={`tab ${view === 'overview' ? 'active' : ''}`} onClick={() => setView('overview')}><Info size={13}/>连接概览</button>}
        {queryTabs.map(tab => <div className="query-tab" key={tab.id}>
          <button className={`tab ${view === 'query' && activeQueryId === tab.id ? 'active' : ''}`} onClick={() => { setActiveQueryId(tab.id); setView('query') }}><span className={`status-dot ${tab.failed ? 'failed' : ''}`}></span>{tab.title}</button>
          <button className="tab-close" title={`关闭 ${tab.title}`} onClick={() => closeQueryTab(tab.id)}><X size={12}/></button>
        </div>)}
        <button className="icon-button new-query-tab" title="新建查询 Tab" onClick={openQueryTab}><Plus size={16}/></button>
        {details && <button className={`tab ${view === 'details' ? 'active' : ''}`} onClick={() => setView('details')}><Table2 size={13}/>{details.name}</button>}
      </div>
      {view === 'query' && <>
        <div className="query-toolbar"><button className="run-button" disabled={!active || busy} onClick={execute}><Play size={15} fill="currentColor"/>{busy ? '执行中' : '运行'}</button><span className="connection-context">{active ? `${active.name} / ${active.database || 'default'}` : '请选择连接'}</span><div className="spacer"/><input ref={importInput} className="hidden-input" type="file" accept=".csv,.json,text/csv,application/json" onChange={e => importData(e.target.files?.[0])}/><button className="tool-button" disabled={!active || active.readonly || busy} onClick={() => importInput.current?.click()}><Upload size={15}/>导入</button><button className="tool-button" disabled={!result} onClick={() => exportData('csv')}><Download size={15}/>CSV</button><button className="tool-button" disabled={!result} onClick={() => exportData('json')}><Download size={15}/>JSON</button></div>
        <section className="editor-wrap"><Editor height="100%" theme="vs-dark" language={language} value={query} onChange={value => activeQuery && updateQueryTab(activeQuery.id, { query: value || '' })} options={{ minimap: { enabled: false }, fontSize: 14, lineHeight: 23, fontFamily: "'JetBrains Mono', Consolas, monospace", padding: { top: 16 }, scrollBeyondLastLine: false, automaticLayout: true }}/></section>
        <section className="results"><div className="result-tabs"><button className={activeQuery?.resultPanel === 'results' ? 'active' : ''} onClick={() => activeQuery && updateQueryTab(activeQuery.id, { resultPanel: 'results' })}>结果</button><button className={`${activeQuery?.resultPanel === 'messages' ? 'active' : ''} ${activeQuery?.failed ? 'message-error' : ''}`} onClick={() => activeQuery && updateQueryTab(activeQuery.id, { resultPanel: 'messages' })}>消息{activeQuery?.failed ? ' · 失败' : ''}</button><div className="spacer"/>{result && activeQuery?.resultPanel === 'results' && <small>{result.row_count} 行 · {result.elapsed_ms} ms{result.truncated ? ' · 已截断' : ''}</small>}</div>{activeQuery?.resultPanel === 'messages' ? <div className={`query-message ${activeQuery.failed ? 'failed' : ''}`}>{activeQuery.message}</div> : <div className="table-wrap">{!result ? <div className="empty-result"><Database size={34}/><span>运行查询后，结果会显示在这里</span></div> : result.columns.length ? <table><thead><tr><th className="row-number">#</th>{result.columns.map(column => <th key={column}>{column}</th>)}</tr></thead><tbody>{result.rows.map((row, rowIndex) => <tr key={rowIndex}><td className="row-number">{rowIndex + 1}</td>{row.map((cell, cellIndex) => <td key={cellIndex}>{displayCell(cell)}</td>)}</tr>)}</tbody></table> : <div className="empty-result"><span>{result.message || '执行完成'}</span></div>}</div>}</section>
      </>}
      {view === 'overview' && <section className="metadata-page">
        {!active ? <div className="empty-result"><Server size={40}/><span>从左侧选择或新建一个数据库连接</span></div> : <>
          <div className="metadata-heading"><div className="metadata-icon"><Database size={25}/></div><div><h1>{active.name}</h1><p>{overview?.label || active.driver} · {active.host}:{active.port || 'default'}</p></div><div className="spacer"/><button className="tool-button" onClick={testConnection}><RefreshCw size={15}/>测试连接</button><button className="tool-button" onClick={openEditConnection}><Pencil size={15}/>编辑连接</button></div>
          {overviewError && <div className="connection-error"><div><strong>无法读取数据库信息</strong><span>{overviewError}</span></div><button onClick={() => { loadOverview(); refreshObjects() }}>重试</button></div>}
          {active.host === 'localhost' && /^\d{1,3}(\.\d{1,3}){3}$/.test(active.name) && <div className="connection-warning"><Info size={16}/><span>连接名称看起来是服务器 IP，但实际主机仍是 localhost。请编辑连接并填写真实主机地址。</span></div>}
          <div className="info-grid"><InfoCard label="服务版本" value={overviewLoading ? '正在读取…' : overview?.version || '读取失败'}/><InfoCard label="当前数据库" value={active.database || '未指定（浏览全部）'}/><InfoCard label="登录用户" value={active.username || '默认用户'}/><InfoCard label="数据库 / 对象" value={overview ? `${overview.database_count ?? treeRoots.length} / ${overview.object_count ?? '-'}` : '-'}/><InfoCard label="连接模式" value={active.readonly ? '只读' : '读写'}/><InfoCard label="驱动" value={overview?.driver || active.driver}/></div>
          <div className="metadata-section"><h3>连接能力</h3><div className="capability-list">{(overview?.capabilities || []).map(item => <span key={item}><CheckCircle2 size={13}/>{item}</span>)}</div></div>
        </>}
      </section>}
      {view === 'details' && details && <section className="metadata-page">
        <div className="metadata-heading"><div className="metadata-icon table"><Table2 size={24}/></div><div><h1>{details.name}</h1><p>{details.schema || active?.database || 'default'} · 表结构</p></div><div className="spacer"/><button className="primary small" onClick={() => queryObject({name: details.name, schema: details.schema, type: 'table'})}>打开数据</button></div>
        <div className="metadata-section"><h3>字段 <small>{details.columns.length}</small></h3><MetadataTable rows={details.columns}/></div>
        <div className="metadata-section"><h3>索引 <small>{details.indexes.length}</small></h3><MetadataTable rows={details.indexes}/></div>
        {details.ddl && <div className="metadata-section"><h3>DDL</h3><pre className="ddl">{details.ddl}</pre></div>}
        {details.type && <div className="metadata-section"><h3>Key 信息</h3><div className="info-grid compact"><InfoCard label="类型" value={details.type}/><InfoCard label="TTL" value={details.ttl ?? -1}/><InfoCard label="内存" value={details.memory_bytes ? `${details.memory_bytes} bytes` : '-'}/></div></div>}
      </section>}
      <footer><span className={notice.includes('失败') ? 'error' : ''}>{notice}</span><span>AllDB 0.1.0</span></footer>
    </main>

    {showForm && <div className="modal-backdrop" onMouseDown={() => setShowForm(false)}><form className="modal" onSubmit={saveConnection} onMouseDown={e => e.stopPropagation()}>
      <div className="modal-head"><div><h2>{editingId ? '编辑数据库连接' : '新建数据库连接'}</h2><p>凭据会加密保存在服务器上</p></div><button type="button" className="icon-button" onClick={() => setShowForm(false)}><X size={18}/></button></div>
      <div className="form-grid"><label className="wide">连接名称<input required value={form.name} onChange={e => setForm({...form, name: e.target.value})} placeholder="例如：生产只读库"/></label><label>数据库类型<select value={form.driver} onChange={e => chooseDriver(e.target.value)}>{drivers.map(driver => <option value={driver.key} key={driver.key}>{driver.label}</option>)}</select></label><label>主机地址<input required value={form.host} onChange={e => setForm({...form, host: e.target.value})}/></label><label>端口<input inputMode="numeric" value={form.port} onChange={e => setForm({...form, port: e.target.value})}/></label><label>数据库 / DB<input value={form.database} onChange={e => setForm({...form, database: e.target.value})} placeholder={form.driver === 'sqlite' ? '/data/demo.db' : 'database'}/></label><label>用户名<input value={form.username} onChange={e => setForm({...form, username: e.target.value})}/></label><label>密码<input type="password" value={form.password} onChange={e => setForm({...form, password: e.target.value})} placeholder={editingId ? '留空则保持原密码' : ''}/></label><label className="checkbox wide"><input type="checkbox" checked={form.readonly} onChange={e => setForm({...form, readonly: e.target.checked})}/><span>只读连接（拦截写入命令）</span></label></div>
      {formTestResult && <div className={`test-result ${formTestResult.includes('成功') ? 'success' : formTestResult.includes('正在') ? '' : 'failed'}`}><KeyRound size={15}/>{formTestResult}</div>}
      <div className="modal-actions"><button type="button" className="secondary test" disabled={formTesting} onClick={testFormConnection}><RefreshCw size={14}/>{formTesting ? '测试中' : '测试连接'}</button><div className="spacer"/><button type="button" className="secondary" onClick={() => setShowForm(false)}>取消</button><button type="submit" className="primary">保存连接</button></div>
    </form></div>}
  </div>
}
