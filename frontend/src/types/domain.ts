export type MeetingStatus = 'PROCESSING' | 'SUCCEEDED' | 'SUCCEEDED_WITH_WARNINGS' | 'FAILED'
export type JobStage = 'QUEUED' | 'PREPROCESSING' | 'TRANSCRIBING' | 'ALIGNING' | 'DIARIZING' | 'ANALYZING' | 'SUCCEEDED' | 'FAILED'
export type DecisionStatus = 'CONFIRMED' | 'PROPOSED' | 'DISPUTED' | 'UNRESOLVED'
export type AssigneeStatus = 'EXPLICIT' | 'INFERRED' | 'UNKNOWN'
export type DueDateStatus = 'EXPLICIT' | 'AMBIGUOUS' | 'UNKNOWN' | 'CONFIRMED'
export type ActionItemStatus = 'TODO' | 'IN_PROGRESS' | 'DONE' | 'CANCELLED'
export type StageEventOutcome = 'RUNNING' | 'COMPLETED' | 'FAILED' | 'INTERRUPTED'
export type DiarizationStatus = 'NOT_RUN' | 'SUCCEEDED' | 'DEGRADED' | 'DISABLED'

export interface TranscriptSegment {
  id: string
  speaker: string
  speakerLabel: string
  startMs: number
  endMs: number
  text: string
}

export interface Decision {
  id: string
  content: string
  status: DecisionStatus
  evidenceText: string | null
  evidenceStartMs: number | null
}

export interface ActionItem {
  id: string
  content: string
  assignee: string | null
  assigneeStatus: AssigneeStatus
  dueDateRaw: string | null
  dueAt: string | null
  duePrecision: string | null
  dueDateStatus: DueDateStatus
  status: ActionItemStatus
  evidenceText: string | null
  evidenceStartMs: number | null
}

export interface MeetingAnalysis {
  summary: string
  decisions: Decision[]
  actionItems: ActionItem[]
  version: number
  provider: string | null
  model: string | null
  promptVersion: string | null
}

export interface AnalysisSnapshotDecision {
  content: string
  status: DecisionStatus
  evidenceText: string | null
  evidenceStartMs: number | null
}

export interface AnalysisSnapshotActionItem {
  content: string
  assignee: string | null
  assigneeStatus: AssigneeStatus
  dueDateRaw: string | null
  dueAt: string | null
  duePrecision: string | null
  dueDateStatus: DueDateStatus
  status: ActionItemStatus
  evidenceText: string | null
  evidenceStartMs: number | null
}

export interface AnalysisSnapshot {
  summary: string
  decisions: AnalysisSnapshotDecision[]
  actionItems: AnalysisSnapshotActionItem[]
}

export interface AnalysisAudit {
  aiOriginal: AnalysisSnapshot | null
  current: AnalysisSnapshot
  changedFields: string[]
  hasChanges: boolean
  currentVersion: number
  provider: string | null
  model: string | null
  promptVersion: string | null
}

export interface ProcessingStageEvent {
  id: number
  stage: JobStage
  attempt: number
  startedAt: string
  finishedAt: string | null
  durationMs: number
  outcome: StageEventOutcome
}

export interface QueueHealth {
  status: string
  redis: string
  workerOnline: boolean
  workerCount: number
  queueLength: number
  intermediateJobCount: number
  startedJobCount: number
  reconciledJobs: number
}

export interface ProcessingJob {
  id: string
  meetingId: string
  stage: JobStage
  progress: number
  message: string
  error: string | null
  errorCode: string | null
  warning: string | null
  diarizationStatus: DiarizationStatus
  speakerCount: number
  retryCount: number
  stageEvents: ProcessingStageEvent[]
  updatedAt: string
}

export interface Meeting {
  id: string
  title: string
  originalFilename: string
  mimeType: string
  fileSize: number
  durationMs: number
  meetingStartedAt: string
  participants: string[]
  context: string
  status: MeetingStatus
  createdAt: string
  updatedAt: string
  transcript: TranscriptSegment[]
  analysis: MeetingAnalysis | null
  job: ProcessingJob | null
}

export interface CreateMeetingInput {
  title: string
  file: File
  meetingStartedAt: string
  participants: string[]
  context: string
  dataProcessingConfirmed: boolean
}

export interface CreateMeetingResult {
  meetingId: string
  jobId: string
  status: JobStage
}

export interface UpdateAnalysisInput {
  summary: string
  decisions: Decision[]
  actionItems: ActionItem[]
  version: number
}
