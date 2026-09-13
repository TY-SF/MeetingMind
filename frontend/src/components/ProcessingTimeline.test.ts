import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ProcessingTimeline from './ProcessingTimeline.vue'
import type { JobStage } from '@/types/domain'

const labels: Array<[JobStage, string]> = [
  ['QUEUED', '已排队'],
  ['PREPROCESSING', '预处理'],
  ['TRANSCRIBING', '语音转录'],
  ['ALIGNING', '时间对齐'],
  ['DIARIZING', '说话人分离'],
  ['ANALYZING', 'AI 整理'],
  ['SUCCEEDED', '处理完成'],
  ['FAILED', '处理失败'],
]

describe('ProcessingTimeline', () => {
  it.each(labels)('maps %s to %s', (stage, label) => {
    expect(mount(ProcessingTimeline, { props: { stage } }).text()).toBe(label)
  })
})
