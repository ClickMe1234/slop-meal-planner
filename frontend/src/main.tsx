import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { registerSW } from 'virtual:pwa-register'
import App from './App'
import './styles.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
    mutations: { retry: 0 }
  }
})

let pendingServiceWorkerUpdate: ((reloadPage?: boolean) => Promise<void>) | null = null
const updateServiceWorker = registerSW({
  immediate: false,
  onNeedRefresh() {
    if (document.body.dataset.unsavedDraft === 'true') {
      pendingServiceWorkerUpdate = updateServiceWorker
      return
    }
    void updateServiceWorker(true)
  },
})

window.addEventListener('slop:draft-state', () => {
  if (document.body.dataset.unsavedDraft !== 'true' && pendingServiceWorkerUpdate) {
    const applyUpdate = pendingServiceWorkerUpdate
    pendingServiceWorkerUpdate = null
    void applyUpdate(true)
  }
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
)
