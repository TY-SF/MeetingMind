import type { Meeting } from '@/types/domain'

export const demoMeetings: Meeting[] = [
  {
    id: 'demo-1', title: '产品迭代周会', originalFilename: 'product-weekly.m4a', mimeType: 'audio/mp4', fileSize: 18_420_000,
    durationMs: 2_430_000, meetingStartedAt: '2026-09-08T14:00:00+08:00', participants: ['张三', '李四', '王五'],
    context: '讨论 2.0 版本范围、发布时间和验收安排。', status: 'SUCCEEDED', createdAt: '2026-09-08T14:02:00+08:00', updatedAt: '2026-09-08T14:08:00+08:00',
    transcript: [
      { id: 't1', speaker: '张三', speakerLabel: 'SPEAKER_00', startMs: 0, endMs: 12400, text: '今天主要确认 2.0 版本的范围和发布时间。' },
      { id: 't2', speaker: '李四', speakerLabel: 'SPEAKER_01', startMs: 13500, endMs: 28600, text: '建议先保留搜索和导出功能，批量上传可以放到下个版本。' },
      { id: 't3', speaker: '王五', speakerLabel: 'SPEAKER_02', startMs: 30100, endMs: 42600, text: '我负责在周五前补齐接口文档和验收清单。' },
      { id: 't4', speaker: '张三', speakerLabel: 'SPEAKER_00', startMs: 44200, endMs: 53100, text: '那就按这个范围推进，目标发布日期定在下周一。' }
    ],
    analysis: {
      summary: '本次会议确认了 2.0 版本的核心范围，优先完成搜索和导出功能，批量上传延后处理。团队将以接口文档和验收清单作为下阶段交付重点。',
      decisions: [{ id: 'd1', content: '2.0 版本优先包含搜索和导出功能，批量上传延后。', status: 'CONFIRMED', evidenceText: '建议先保留搜索和导出功能，批量上传可以放到下个版本。', evidenceStartMs: 13500 }],
      actionItems: [{ id: 'a1', content: '补齐接口文档和验收清单', assignee: '王五', assigneeStatus: 'EXPLICIT', dueDateRaw: '周五前', dueAt: '2026-09-11T15:59:59+08:00', duePrecision: 'DAY', dueDateStatus: 'EXPLICIT', status: 'TODO', evidenceText: '我负责在周五前补齐接口文档和验收清单。', evidenceStartMs: 30100 }], version: 1, provider: 'mock', model: 'demo-model', promptVersion: 'mock-v1'
    },
    job: { id: 'job-1', meetingId: 'demo-1', stage: 'SUCCEEDED', progress: 100, message: '处理完成', error: null, errorCode: null, retryCount: 0, stageEvents: [], warning: null, diarizationStatus: 'SUCCEEDED', speakerCount: 3, updatedAt: '2026-09-08T14:08:00+08:00' }
  },
  {
    id: 'demo-2', title: '技术方案讨论', originalFilename: 'architecture.wav', mimeType: 'audio/wav', fileSize: 24_000_000,
    durationMs: 3_100_000, meetingStartedAt: '2026-09-07T10:00:00+08:00', participants: ['赵敏', '陈杰'], context: '比较两种异步任务实现方案。', status: 'SUCCEEDED_WITH_WARNINGS', createdAt: '2026-09-07T10:02:00+08:00', updatedAt: '2026-09-07T10:12:00+08:00',
    transcript: [{ id: 't2-1', speaker: 'SPEAKER_00', speakerLabel: 'SPEAKER_00', startMs: 0, endMs: 16500, text: '我们需要优先保证任务状态能够持久化。' }],
    analysis: { summary: '会议完成了方案初步比较，但由于说话人分离质量不足，部分发言人标签需要人工确认。', decisions: [{ id: 'd2', content: '优先验证任务状态持久化方案。', status: 'PROPOSED', evidenceText: '我们需要优先保证任务状态能够持久化。', evidenceStartMs: 0 }], actionItems: [], version: 1, provider: 'mock', model: 'demo-model', promptVersion: 'mock-v1' },
    job: { id: 'job-2', meetingId: 'demo-2', stage: 'SUCCEEDED', progress: 100, message: '处理完成，但存在警告', error: null, errorCode: null, retryCount: 0, stageEvents: [], warning: '说话人分离未完全成功，部分标签为 SPEAKER_00。', diarizationStatus: 'DEGRADED', speakerCount: 1, updatedAt: '2026-09-07T10:12:00+08:00' }
  }
]

