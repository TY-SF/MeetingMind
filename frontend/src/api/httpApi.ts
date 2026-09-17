import { authorizationHeader, notifyAccessTokenRequired } from './accessToken'
import type { MeetingApi } from '@/types/api'
import type {
  ActionItem,
  AnalysisAudit,
  AnalysisSnapshot,
  CreateMeetingInput,
  CreateMeetingResult,
  Decision,
  Meeting,
  MeetingAnalysis,
  ProcessingJob,
  ProcessingStageEvent,
  QueueHealth,
  UpdateAnalysisInput,
} from '@/types/domain'

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

type ApiErrorBody = { detail?: string | { code?: string; message?: string } }

type RawDecision = {
  id: string
  content: string
  status: Decision['status']
  evidence_text: string | null
  evidence_start_ms: number | null
}
type RawActionItem = {
  id: string
  content: string
  assignee: string | null
  assignee_status: ActionItem['assigneeStatus']
  due_date_raw: string | null
  due_at: string | null
  due_precision: string | null
  due_date_status: ActionItem['dueDateStatus']
  status: ActionItem['status']
  evidence_text: string | null
  evidence_start_ms: number | null
}
type RawAnalysisSnapshot = {
  summary: string
  decisions: Array<Omit<RawDecision, 'id'>>
  action_items: Array<Omit<RawActionItem, 'id'>>
}
type RawAnalysisAudit = {
  ai_original: RawAnalysisSnapshot | null
  current: RawAnalysisSnapshot
  changed_fields: string[]
  has_changes: boolean
  current_version: number
  provider?: string | null
  model?: string | null
  prompt_version?: string | null
}
type RawAnalysis = {
  summary: string
  decisions: RawDecision[]
  action_items: RawActionItem[]
  version: number
  provider?: string | null
  model?: string | null
  prompt_version?: string | null
}
type RawStageEvent = {
  id: number
  stage: ProcessingJob['stage']
  attempt: number
  started_at: string
  finished_at?: string | null
  duration_ms: number
  outcome: ProcessingStageEvent['outcome']
}
type RawQueueHealth = {
  status: string
  redis: string
  worker_online: boolean
  worker_count: number
  queue_length: number
  intermediate_job_count: number
  started_job_count: number
  reconciled_jobs?: number
}

type RawJob = {
  id: string
  meeting_id: string
  stage: ProcessingJob['stage']
  progress: number
  message: string
  error?: string | null
  error_code?: string | null
  warning?: string | null
  diarization_status?: ProcessingJob['diarizationStatus']
  speaker_count?: number
  retry_count?: number
  stage_events?: RawStageEvent[]
  updated_at: string
}
type RawMeeting = {
  id: string
  title: string
  original_filename: string
  mime_type: string
  file_size: number
  duration_ms: number
  meeting_started_at: string
  participants: string[]
  context: string
  status: Meeting['status']
  created_at: string
  updated_at: string
  transcript: Array<{ id: string; speaker: string; speaker_label: string; start_ms: number; end_ms: number; text: string }>
  analysis: RawAnalysis | null
  job: RawJob | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...authorizationHeader(), ...init.headers },
    })
  } catch {
    throw new Error('无法连接后端服务。请确认 MeetingMind 后端已启动。')
  }

  if (response.status === 204) return undefined as T
  const payload: unknown = await response.json().catch(() => null)
  handleAuthenticationFailure(payload, response.status)
  if (!response.ok) throw new Error(readErrorMessage(payload, response.status))
  return payload as T
}

async function download(path: string, fallbackFilename: string): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}${path}`, { headers: { Accept: '*/*', ...authorizationHeader() } })
  } catch {
    throw new Error('无法连接后端服务。请确认 MeetingMind 后端已启动。')
  }
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null)
    handleAuthenticationFailure(payload, response.status)
    throw new Error(readErrorMessage(payload, response.status))
  }
  const blob = await response.blob()
  const href = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = filenameFromDisposition(response.headers.get('content-disposition')) || fallbackFilename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(href)
}

function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null
  const encoded = header.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  if (encoded) {
    try { return decodeURIComponent(encoded) } catch { return null }
  }
  return header.match(/filename="?([^";]+)"?/i)?.[1] || null
}

function handleAuthenticationFailure(payload: unknown, status: number): void {
  if (status !== 401 || !isRecord(payload) || !isRecord(payload.detail)) return
  const code = typeof payload.detail.code === 'string' ? payload.detail.code : ''
  if (code === 'ACCESS_TOKEN_REQUIRED' || code === 'ACCESS_TOKEN_INVALID') {
    notifyAccessTokenRequired(code === 'ACCESS_TOKEN_INVALID')
  }
}

function readErrorMessage(payload: unknown, status: number): string {
  if (isRecord(payload) && 'detail' in payload) {
    const detail = (payload as ApiErrorBody).detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail.message === 'string') return detail.message
  }
  return `请求失败（HTTP ${status}）`
}

function toDecision(item: RawDecision): Decision {
  return {
    id: item.id,
    content: item.content,
    status: item.status,
    evidenceText: item.evidence_text,
    evidenceStartMs: item.evidence_start_ms,
  }
}

function toActionItem(item: RawActionItem): ActionItem {
  return {
    id: item.id,
    content: item.content,
    assignee: item.assignee,
    assigneeStatus: item.assignee_status,
    dueDateRaw: item.due_date_raw,
    dueAt: item.due_at,
    duePrecision: item.due_precision,
    dueDateStatus: item.due_date_status,
    status: item.status,
    evidenceText: item.evidence_text,
    evidenceStartMs: item.evidence_start_ms,
  }
}

function toAnalysisSnapshot(item: RawAnalysisSnapshot): AnalysisSnapshot {
  return {
    summary: item.summary,
    decisions: item.decisions.map((decision) => ({
      content: decision.content,
      status: decision.status,
      evidenceText: decision.evidence_text,
      evidenceStartMs: decision.evidence_start_ms,
    })),
    actionItems: item.action_items.map((action) => ({
      content: action.content,
      assignee: action.assignee,
      assigneeStatus: action.assignee_status,
      dueDateRaw: action.due_date_raw,
      dueAt: action.due_at,
      duePrecision: action.due_precision,
      dueDateStatus: action.due_date_status,
      status: action.status,
      evidenceText: action.evidence_text,
      evidenceStartMs: action.evidence_start_ms,
    })),
  }
}

function toAnalysisAudit(item: RawAnalysisAudit): AnalysisAudit {
  return {
    aiOriginal: item.ai_original ? toAnalysisSnapshot(item.ai_original) : null,
    current: toAnalysisSnapshot(item.current),
    changedFields: item.changed_fields,
    hasChanges: item.has_changes,
    currentVersion: item.current_version,
    provider: item.provider ?? null,
    model: item.model ?? null,
    promptVersion: item.prompt_version ?? null,
  }
}

function toAnalysis(item: RawAnalysis): MeetingAnalysis {
  return {
    summary: item.summary,
    decisions: item.decisions.map(toDecision),
    actionItems: item.action_items.map(toActionItem),
    version: item.version,
    provider: item.provider ?? null,
    model: item.model ?? null,
    promptVersion: item.prompt_version ?? null,
  }
}

function toStageEvent(item: RawStageEvent): ProcessingStageEvent {
  return {
    id: item.id,
    stage: item.stage,
    attempt: item.attempt,
    startedAt: item.started_at,
    finishedAt: item.finished_at ?? null,
    durationMs: item.duration_ms ?? 0,
    outcome: item.outcome,
  }
}

function toJob(item: RawJob): ProcessingJob {
  return {
    id: item.id,
    meetingId: item.meeting_id,
    stage: item.stage,
    progress: item.progress,
    message: item.message,
    error: item.error ?? null,
    errorCode: item.error_code ?? null,
    warning: item.warning ?? null,
    diarizationStatus: item.diarization_status ?? 'NOT_RUN',
    speakerCount: item.speaker_count ?? 0,
    retryCount: item.retry_count ?? 0,
    stageEvents: (item.stage_events ?? []).map(toStageEvent),
    updatedAt: item.updated_at,
  }
}

function toMeeting(item: RawMeeting): Meeting {
  return {
    id: item.id,
    title: item.title,
    originalFilename: item.original_filename,
    mimeType: item.mime_type,
    fileSize: item.file_size,
    durationMs: item.duration_ms,
    meetingStartedAt: item.meeting_started_at,
    participants: item.participants,
    context: item.context,
    status: item.status,
    createdAt: item.created_at,
    updatedAt: item.updated_at,
    transcript: item.transcript.map((segment) => ({
      id: segment.id,
      speaker: segment.speaker,
      speakerLabel: segment.speaker_label,
      startMs: segment.start_ms,
      endMs: segment.end_ms,
      text: segment.text,
    })),
    analysis: item.analysis ? toAnalysis(item.analysis) : null,
    job: item.job ? toJob(item.job) : null,
  }
}

function toUpdatePayload(input: UpdateAnalysisInput) {
  return {
    summary: input.summary.trim(),
    version: input.version,
    decisions: input.decisions.map((item) => ({
      id: item.id.startsWith('new-') ? undefined : item.id,
      content: item.content.trim(),
      status: item.status,
      evidence_text: item.evidenceText || null,
      evidence_start_ms: item.evidenceStartMs,
    })),
    action_items: input.actionItems.map((item) => ({
      id: item.id.startsWith('new-') ? undefined : item.id,
      content: item.content.trim(),
      assignee: item.assignee?.trim() || null,
      assignee_status: item.assigneeStatus,
      due_date_raw: item.dueDateRaw?.trim() || null,
      due_at: item.dueAt,
      due_precision: item.duePrecision,
      due_date_status: item.dueDateStatus,
      status: item.status,
      evidence_text: item.evidenceText || null,
      evidence_start_ms: item.evidenceStartMs,
    })),
  }
}

export const httpApi: MeetingApi = {
  async listMeetings() {
    return (await request<RawMeeting[]>('/meetings')).map(toMeeting)
  },
  async getMeeting(id) {
    return toMeeting(await request<RawMeeting>(`/meetings/${encodeURIComponent(id)}`))
  },
  async createMeeting(input: CreateMeetingInput): Promise<CreateMeetingResult> {
    const form = new FormData()
    form.append('file', input.file)
    form.append('title', input.title.trim())
    form.append('meeting_started_at', input.meetingStartedAt)
    form.append('participants', JSON.stringify(input.participants))
    form.append('context', input.context.trim())
    form.append('data_processing_confirmed', String(input.dataProcessingConfirmed))
    const payload = await request<{ meeting_id: string; job_id: string; status: CreateMeetingResult['status'] }>('/meetings', {
      method: 'POST',
      body: form,
    })
    return { meetingId: payload.meeting_id, jobId: payload.job_id, status: payload.status }
  },
  async getProcessingJob(id) {
    return toJob(await request<RawJob>(`/jobs/${encodeURIComponent(id)}`))
  },
  async retryProcessingJob(id) {
    return toJob(await request<RawJob>(`/jobs/${encodeURIComponent(id)}/retry`, { method: 'POST' }))
  },
  async getQueueHealth(): Promise<QueueHealth> {
    const item = await request<RawQueueHealth>('/health/queue')
    return {
      status: item.status,
      redis: item.redis,
      workerOnline: item.worker_online,
      workerCount: item.worker_count,
      queueLength: item.queue_length,
      intermediateJobCount: item.intermediate_job_count,
      startedJobCount: item.started_job_count,
      reconciledJobs: item.reconciled_jobs ?? 0,
    }
  },
  async generateAnalysis(id, analysisDataConfirmed) {
    return toAnalysis(await request<RawAnalysis>(`/meetings/${encodeURIComponent(id)}/analysis`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ analysis_data_confirmed: analysisDataConfirmed }),
    }))
  },
  async getAnalysisAudit(id) {
    return toAnalysisAudit(await request<RawAnalysisAudit>(`/meetings/${encodeURIComponent(id)}/analysis/audit`))
  },
  async updateAnalysis(id, input) {
    return toAnalysis(await request<RawAnalysis>(`/meetings/${encodeURIComponent(id)}/analysis`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(toUpdatePayload(input)),
    }))
  },
  async updateSpeakers(id, mappings) {
    const meeting = await request<RawMeeting>(`/meetings/${encodeURIComponent(id)}/speakers`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mappings: mappings.map((item) => ({ speaker_label: item.speakerLabel, speaker_name: item.speakerName.trim() })) }),
    })
    return toMeeting(meeting)
  },
  async downloadMarkdown(id) {
    await download(`/meetings/${encodeURIComponent(id)}/exports/markdown`, 'meeting.md')
  },
  async downloadCalendar(id) {
    await download(`/meetings/${encodeURIComponent(id)}/exports/calendar`, 'meeting.ics')
  },
  async deleteMeeting(id) {
    await request<void>(`/meetings/${encodeURIComponent(id)}`, { method: 'DELETE' })
  },
}
