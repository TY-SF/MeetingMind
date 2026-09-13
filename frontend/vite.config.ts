import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  return {
    plugins: [vue()],
    resolve: { alias: { '@': '/src' } },
    build: {
      chunkSizeWarningLimit: 500,
      rollupOptions: {
        output: {
          manualChunks: {
            'vue-vendor': ['vue', 'vue-router', 'pinia'],
            'element-plus-icons': ['@element-plus/icons-vue'],
          },
        },
      },
    },
    test: { environment: 'jsdom', globals: true, include: ['src/**/*.test.ts'] },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: env.MEETINGMIND_BACKEND_URL || 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
  }
})
