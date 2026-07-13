import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['meal-mark.svg'],
      manifest: {
        name: 'Savour Meal Planner',
        short_name: 'Savour',
        description: 'Private household meal planning, pantry and shopping.',
        theme_color: '#2e6b45',
        background_color: '#f7f5ef',
        display: 'standalone',
        start_url: '/week',
        icons: [
          { src: '/meal-mark.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any maskable' }
        ]
      },
      workbox: {
        navigateFallback: '/index.html',
        runtimeCaching: [
          {
            urlPattern: ({ request }) => request.destination === 'image',
            handler: 'CacheFirst',
            options: { cacheName: 'recipe-images', expiration: { maxEntries: 60, maxAgeSeconds: 604800 } }
          }
        ]
      }
    })
  ],
  server: {
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } }
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true
  }
})
