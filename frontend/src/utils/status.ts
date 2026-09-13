import type { MeetingStatus } from '@/types/domain'
export const statusLabel: Record<MeetingStatus, string> = { PROCESSING: '处理中', SUCCEEDED: '已完成', SUCCEEDED_WITH_WARNINGS: '有警告', FAILED: '处理失败' }
export const statusType: Record<MeetingStatus, '' | 'success' | 'warning' | 'danger' | 'info'> = { PROCESSING: 'info', SUCCEEDED: 'success', SUCCEEDED_WITH_WARNINGS: 'warning', FAILED: 'danger' }
