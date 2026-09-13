import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import StageDurationList from './StageDurationList.vue'
import type { ProcessingStageEvent } from '@/types/domain'

const events: ProcessingStageEvent[] = [
  { id: 1, stage: 'QUEUED', attempt: 0, startedAt: '2026-09-09T02:00:00Z', finishedAt: '2026-09-09T02:00:01Z', durationMs: 1000, outcome: 'COMPLETED' },
  { id: 2, stage: 'PREPROCESSING', attempt: 1, startedAt: '2026-09-09T02:00:01Z', finishedAt: null, durationMs: 2400, outcome: 'RUNNING' },
]

const global = {
  stubs: {
    'el-tag': { template: '<span><slot /></span>' },
    'el-empty': { props: ['description'], template: '<div>{{ description }}</div>' },
  },
}

describe('StageDurationList', () => {
  it('renders persisted stage duration and retry information', () => {
    const wrapper = mount(StageDurationList, { props: { events }, global })
    expect(wrapper.text()).toContain('排队等待')
    expect(wrapper.text()).toContain('1.0 秒')
    expect(wrapper.text()).toContain('自动恢复第 1 次')
    expect(wrapper.text()).toContain('进行中')
  })

  it('explains when no verifiable timing history exists', () => {
    const wrapper = mount(StageDurationList, { props: { events: [] }, global })
    expect(wrapper.text()).toContain('暂无可验证的阶段耗时记录')
  })
})
