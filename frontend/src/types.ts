export type Driver = {
  key: string
  label: string
  default_port: number | null
  query_language: string
  capabilities: string[]
}

export type Connection = {
  id: string
  name: string
  driver: string
  host: string
  port: number | null
  database: string
  username: string
  options: Record<string, unknown>
  readonly: boolean
  created_at: string
  updated_at: string
}

export type DbObject = { name: string; type: string; schema?: string; parent?: string; ttl?: number }
export type TreeNode = {
  id: string; name: string; type: string; has_children: boolean; database?: string
  schema?: string; table?: string; data_type?: string; key?: string; nullable?: string
}
export type ConnectionOverview = {
  ok: boolean; version: string; driver: string; label: string; host: string; port?: number
  database: string; username: string; capabilities: string[]; object_count?: number
  database_count?: number; size_bytes?: number; memory_used?: string; mode?: string
}
export type ObjectDetails = {
  schema: string; name: string; type?: string; ttl?: number; memory_bytes?: number
  sample?: unknown; columns: Record<string, unknown>[]; indexes: Record<string, unknown>[]; ddl: string
}
export type QueryResult = {
  columns: string[]
  rows: unknown[][]
  row_count: number
  truncated: boolean
  elapsed_ms: number
  message: string
}
