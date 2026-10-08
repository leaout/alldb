import type { Connection, ConnectionOverview, DbObject, Driver, ObjectDetails, QueryResult, TreeNode } from './types'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 30000)
  try {
    const response = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...init, signal: controller.signal })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `请求失败 (${response.status})`)
    }
    return response.status === 204 ? (undefined as T) : response.json()
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw new Error('连接请求超时（30 秒）')
    throw error
  } finally {
    window.clearTimeout(timeout)
  }
}

export const api = {
  drivers: () => request<Driver[]>('/api/drivers'),
  connections: () => request<Connection[]>('/api/connections'),
  createConnection: (value: object) => request<Connection>('/api/connections', { method: 'POST', body: JSON.stringify(value) }),
  testUnsavedConnection: (value: object, existingId = '') => request<{ok: boolean; version: string}>(`/api/connections/test${existingId ? `?existing_id=${encodeURIComponent(existingId)}` : ''}`, { method: 'POST', body: JSON.stringify(value) }),
  updateConnection: (id: string, value: object) => request<Connection>(`/api/connections/${id}`, { method: 'PUT', body: JSON.stringify(value) }),
  deleteConnection: (id: string) => request<void>(`/api/connections/${id}`, { method: 'DELETE' }),
  testConnection: (id: string) => request<{ok: boolean; version: string}>(`/api/connections/${id}/test`, { method: 'POST' }),
  objects: (id: string) => request<DbObject[]>(`/api/connections/${id}/objects`),
  overview: (id: string) => request<ConnectionOverview>(`/api/connections/${id}/overview`),
  objectDetails: (id: string, name: string, schema = '') => request<ObjectDetails>(`/api/connections/${id}/object-details?name=${encodeURIComponent(name)}&schema=${encodeURIComponent(schema)}`),
  tree: (id: string, node?: Partial<TreeNode>) => {
    const params = new URLSearchParams({ node_type: node?.type || 'root', database: node?.database || '', schema: node?.schema || '', table: node?.table || '' })
    return request<TreeNode[]>(`/api/connections/${id}/tree?${params}`)
  },
  query: (connection_id: string, query: string) => request<QueryResult>('/api/query', {
    method: 'POST', body: JSON.stringify({ connection_id, query, max_rows: 1000 }),
  }),
  importData: async (connectionId: string, table: string, file: File) => {
    const body = new FormData()
    body.append('connection_id', connectionId); body.append('table', table); body.append('file', file)
    const response = await fetch('/api/import', { method: 'POST', body })
    const value = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(value.detail || `导入失败 (${response.status})`)
    return value as { imported: number; table: string; columns: string[] }
  },
  exportUrl: '/api/export',
}
