import React from 'react'
import ReactDOM from 'react-dom/client'
import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import 'monaco-editor/esm/vs/basic-languages/sql/sql.contribution'
import 'monaco-editor/esm/vs/basic-languages/cypher/cypher.contribution'
import 'monaco-editor/esm/vs/basic-languages/shell/shell.contribution'
import App from './App'
import './styles.css'

self.MonacoEnvironment = {
  getWorker() { return new EditorWorker() },
}
loader.config({ monaco })

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
