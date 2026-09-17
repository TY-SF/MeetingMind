import { demoMeetings } from '@/mocks/fixtures'
import type { MeetingApi } from '@/types/api'
import type { CreateMeetingInput, Meeting, MeetingAnalysis, ProcessingJob, UpdateAnalysisInput } from '@/types/domain'

const STORAGE_KEY = 'meetingmind-prototype-meetings'
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const now = () => new Date().toISOString()

function load(): Meeting[] {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) { localStorage.setItem(STORAGE_KEY, JSON.stringify(demoMeetings)); return clone(demoMeetings) }
  try { return JSON.parse(raw) as Meeting[] } catch { return clone(demoMeetings) }
}
function save(meetings: Meeting[]) { localStorage.setItem(STORAGE_KEY, JSON.stringify(meetings)) }
function getById(id: string) {
  const meeting = load().find((item) => item.id === id)
  if (!meeting) throw new Error('会议不存在或已被删除')
  return meeting
}

export const mockApi: MeetingApi = {
  async listMeetings() { await wait(100); return clone(load()).sort((a, b) => b.createdAt.localeCompare(a.createdAt)) },
  async getMeeting(id) { await wait(100); return clone(getById(id)) },
  async createMeeting(input: CreateMeetingInput) {
    await wait(200)
    const id = `meeting-${Date.now()}`; const createdAt = now()
    const meeting: Meeting = {
      id, title: input.title, originalFilename: input.file.name, mimeType: input.file.type || 'audio/mpeg', fileSize: input.file.size,
      durationMs: 0, meetingStartedAt: input.meetingStartedAt, participants: input.participants, context: input.context,
      status: 'PROCESSING', createdAt, updatedAt: createdAt, transcript: [], analysis: null,
      job: { id: `job-${id}`, meetingId: id, stage: 'QUEUED', progress: 8, message: '任务已进入队列', error: null, errorCode: null, retryCount: 0, stageEvents: [], warning: null, diarizationStatus: 'NOT_RUN', speakerCount: 0, updatedAt: createdAt },
    }
    const meetings = load(); meetings.push(meeting); save(meetings)
    return { meetingId: id, jobId: `job-${id}`, status: 'QUEUED' }
  },
  async getProcessingJob(id): Promise<ProcessingJob> { await wait(100); return clone(getById(id).job!) },
  async retryProcessingJob(id): Promise<ProcessingJob> {
    await wait(100); const meetings = load(); const meeting = meetings.find((item) => item.job?.id === id)
    if (!meeting?.job) throw new Error('任务不存在')
    const updatedAt = now(); const job = meeting.job
    job.stage = 'QUEUED'; job.progress = 8; job.message = '任务已重新进入队列'; job.error = null; job.errorCode = null; job.retryCount += 1; job.updatedAt = updatedAt
    meeting.status = 'PROCESSING'; meeting.updatedAt = updatedAt; save(meetings); return clone(job)
  },
  async getQueueHealth() { await wait(50); return { status: 'ready', redis: 'mock', workerOnline: true, workerCount: 1, queueLength: 0, intermediateJobCount: 0, startedJobCount: 0, reconciledJobs: 0 } },
  async generateAnalysis(id, _analysisDataConfirmed): Promise<MeetingAnalysis> {
    await wait(200); const meetings = load(); const index = meetings.findIndex((meeting) => meeting.id === id)
    if (index < 0) throw new Error('会议不存在或已被删除')
    const analysis: MeetingAnalysis = { summary: '这是 Mock 模式生成的会议摘要。', decisions: [], actionItems: [], version: 1, provider: 'mock', model: 'demo-model', promptVersion: 'mock-v1' }
    meetings[index].analysis = analysis; meetings[index].status = 'SUCCEEDED'; meetings[index].updatedAt = now(); save(meetings)
    return clone(analysis)
  },
  async getAnalysisAudit(id) {
    await wait(100)
    const meeting = getById(id)
    if (!meeting.analysis) throw new Error('会议尚未生成分析结果')
    const snapshot = {
      summary: meeting.analysis.summary,
      decisions: meeting.analysis.decisions.map(({ id: _id, ...item }) => item),
      actionItems: meeting.analysis.actionItems.map(({ id: _id, ...item }) => item),
    }
    return {
      aiOriginal: snapshot,
      current: snapshot,
      changedFields: [],
      hasChanges: false,
      currentVersion: meeting.analysis.version,
      provider: meeting.analysis.provider,
      model: meeting.analysis.model,
      promptVersion: meeting.analysis.promptVersion,
    }
  },
  async updateAnalysis(id, input): Promise<MeetingAnalysis> {
    await wait(100); const meetings = load(); const index = meetings.findIndex((meeting) => meeting.id === id)
    if (index < 0 || !meetings[index].analysis) throw new Error('会议尚未生成分析结果')
    const current = meetings[index].analysis!
    if (current.version !== input.version) throw new Error('分析版本已变更，请重新加载后再保存')
    const analysis = { ...clone(input), version: input.version + 1, provider: current.provider, model: current.model, promptVersion: current.promptVersion }
    meetings[index].analysis = analysis; meetings[index].updatedAt = now(); save(meetings)
    return clone(analysis)
  },
  async updateSpeakers(id, mappings) {
    await wait(100)
    const meetings = load()
    const index = meetings.findIndex((meeting) => meeting.id === id)
    if (index < 0) throw new Error('会议不存在或已被删除')
    const names = new Map(mappings.map((item) => [item.speakerLabel, item.speakerName]))
    meetings[index].transcript = meetings[index].transcript.map((segment) => ({ ...segment, speaker: names.get(segment.speaker) || segment.speaker }))
    meetings[index].updatedAt = now()
    save(meetings)
    return clone(meetings[index])
  },
  async downloadMarkdown() { throw new Error('Mock 模式不支持导出') },
  async downloadCalendar() { throw new Error('Mock 模式不支持导出') },
  async deleteMeeting(id) { await wait(100); save(load().filter((meeting) => meeting.id !== id)) },
}
