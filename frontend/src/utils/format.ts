export function formatDate(value: string) { return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) }
export function formatDateInput(value: string) { return value.slice(0, 16) }
export function formatDuration(ms: number) { if (!ms) return '待处理'; const minutes = Math.floor(ms / 60000); const seconds = Math.floor((ms % 60000) / 1000); return `${minutes}分${seconds.toString().padStart(2, '0')}秒` }
export function formatBytes(bytes: number) { if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`; return `${(bytes / 1024 / 1024).toFixed(1)} MB` }
export function formatTimestamp(ms: number) { const total = Math.floor(ms / 1000); return `${Math.floor(total / 60).toString().padStart(2, '0')}:${(total % 60).toString().padStart(2, '0')}` }


export function formatStageDuration(ms: number) {
  if (ms < 1000) return `${Math.max(0, ms)} 毫秒`
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} 秒`
  const minutes = Math.floor(ms / 60000)
  const seconds = Math.floor((ms % 60000) / 1000)
  return `${minutes} 分 ${seconds.toString().padStart(2, '0')} 秒`
}
