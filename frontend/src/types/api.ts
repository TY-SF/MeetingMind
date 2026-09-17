import type { AnalysisAudit, CreateMeetingInput, CreateMeetingResult, Meeting, MeetingAnalysis, ProcessingJob, QueueHealth, UpdateAnalysisInput } from './domain'

export interface MeetingApi {
  listMeetings(): Promise<Meeting[]>
  getMeeting(id: string): Promise<Meeting>
  createMeeting(input: CreateMeetingInput): Promise<CreateMeetingResult>
  getProcessingJob(id: string): Promise<ProcessingJob>
  retryProcessingJob(id: string): Promise<ProcessingJob>
  getQueueHealth(): Promise<QueueHealth>
  generateAnalysis(id: string, analysisDataConfirmed: boolean): Promise<MeetingAnalysis>
  getAnalysisAudit(id: string): Promise<AnalysisAudit>
  updateAnalysis(id: string, input: UpdateAnalysisInput): Promise<MeetingAnalysis>
  updateSpeakers(id: string, mappings: Array<{ speakerLabel: string; speakerName: string }>): Promise<Meeting>
  downloadMarkdown(id: string): Promise<void>
  downloadCalendar(id: string): Promise<void>
  deleteMeeting(id: string): Promise<void>
}
