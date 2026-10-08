/// <reference types="vite/client" />

interface Window {
  MonacoEnvironment?: {
    getWorker(moduleId: string, label: string): Worker
  }
}
