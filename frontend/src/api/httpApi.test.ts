import { afterEach, describe, expect, it, vi } from 'vitest'
import { httpApi } from './httpApi'

afterEach(() => vi.unstubAllGlobals())

describe('httpApi processing job mapping', () => {
  it('maps persisted stage event fields without losing timing data', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 'job-1',
        meeting_id: 'meeting-1',
        stage: 'TRANSCRIBING',
        progress: 48,
        message: '正在转录',
        error: null,
        error_code: null,
        warning: null,
        retry_count: 1,
        stage_events: [{
          id: 7,
          stage: 'PREPROCESSING',
          attempt: 1,
          started_at: '2026-09-09T02:00:00+00:00',
          finished_at: '2026-09-09T02:00:03+00:00',
          duration_ms: 3000,
          outcome: 'COMPLETED',
        }],
        updated_at: '2026-09-09T02:00:03+00:00',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const job = await httpApi.getProcessingJob('job/1')

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/jobs/job%2F1', expect.objectContaining({ headers: { Accept: 'application/json' } }))
    expect(job.retryCount).toBe(1)
    expect(job.stageEvents).toEqual([{
      id: 7,
      stage: 'PREPROCESSING',
      attempt: 1,
      startedAt: '2026-09-09T02:00:00+00:00',
      finishedAt: '2026-09-09T02:00:03+00:00',
      durationMs: 3000,
      outcome: 'COMPLETED',
    }])
  })

  it('keeps compatibility with jobs created before stage timing migration', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 'legacy-job', meeting_id: 'meeting-1', stage: 'SUCCEEDED', progress: 100, message: '完成',
        retry_count: 0, updated_at: '2026-09-09T02:00:03+00:00',
      }),
    }))

    const job = await httpApi.getProcessingJob('legacy-job')
    expect(job.stageEvents).toEqual([])
  })
})

describe('httpApi privacy acknowledgements', () => {
  it('includes the recording-processing acknowledgement in upload form data', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ meeting_id: 'meeting-1', job_id: 'job-1', status: 'QUEUED' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await httpApi.createMeeting({
      title: '隐私边界验证',
      file: new File(['audio'], 'meeting.wav', { type: 'audio/wav' }),
      meetingStartedAt: '2026-09-17T10:00:00.000Z',
      participants: ['张三'],
      context: '测试',
      dataProcessingConfirmed: true,
    })

    const [, options] = fetchMock.mock.calls[0]
    const form = options.body as FormData
    expect(form.get('data_processing_confirmed')).toBe('true')
  })

  it('sends an explicit acknowledgement for every AI analysis request', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        summary: '摘要', decisions: [], action_items: [], version: 1,
        provider: 'test', model: 'test-model', prompt_version: 'v1',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await httpApi.generateAnalysis('meeting/1', true)

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/meetings/meeting%2F1/analysis', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ analysis_data_confirmed: true }),
    }))
  })
})
