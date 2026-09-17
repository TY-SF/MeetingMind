import { defineStore } from 'pinia'
import { meetingApi } from '@/api/api'
import type { CreateMeetingInput, Meeting, MeetingAnalysis, UpdateAnalysisInput } from '@/types/domain'

function messageFor(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

export const useMeetingStore = defineStore('meeting', {
  state: () => ({ meetings: [] as Meeting[], current: null as Meeting | null, loading: false, error: '' }),
  actions: {
    async fetchMeetings() {
      this.loading = true; this.error = ''
      try { this.meetings = await meetingApi.listMeetings() }
      catch (error) { this.error = messageFor(error, '加载会议列表失败') }
      finally { this.loading = false }
    },
    async fetchMeeting(id: string) {
      this.loading = true; this.error = ''
      try { this.current = await meetingApi.getMeeting(id); return this.current }
      catch (error) { this.error = messageFor(error, '加载会议失败'); throw error }
      finally { this.loading = false }
    },
    async createMeeting(input: CreateMeetingInput) {
      this.error = ''
      try {
        const created = await meetingApi.createMeeting(input)
        const meeting = await meetingApi.getMeeting(created.meetingId)
        this.current = meeting
        this.meetings = [meeting, ...this.meetings.filter((item) => item.id !== meeting.id)]
        return meeting
      } catch (error) { this.error = messageFor(error, '上传会议失败'); throw error }
    },
    async refreshMeeting(id: string) {
      const meeting = await meetingApi.getMeeting(id)
      this.current = meeting
      const index = this.meetings.findIndex((item) => item.id === id)
      if (index >= 0) this.meetings[index] = meeting
      return meeting
    },
    async retryProcessingJob(id: string) {
      this.error = ''
      try {
        const job = await meetingApi.retryProcessingJob(id)
        if (this.current?.job?.id === id) this.current.job = job
        return job
      } catch (error) { this.error = messageFor(error, '重新处理任务失败'); throw error }
    },
    async generateAnalysis(id: string, analysisDataConfirmed: boolean): Promise<MeetingAnalysis> {
      this.error = ''
      try {
        const analysis = await meetingApi.generateAnalysis(id, analysisDataConfirmed)
        await this.refreshMeeting(id)
        return analysis
      } catch (error) { this.error = messageFor(error, '生成 AI 分析失败'); throw error }
    },
    async updateSpeakers(id: string, mappings: Array<{ speakerLabel: string; speakerName: string }>) {
      this.error = ''
      try {
        const meeting = await meetingApi.updateSpeakers(id, mappings)
        this.current = meeting
        const index = this.meetings.findIndex((item) => item.id === id)
        if (index >= 0) this.meetings[index] = meeting
        return meeting
      } catch (error) { this.error = messageFor(error, '保存说话人映射失败'); throw error }
    },
    async updateAnalysis(id: string, input: UpdateAnalysisInput): Promise<MeetingAnalysis> {
      this.error = ''
      try {
        const analysis = await meetingApi.updateAnalysis(id, input)
        await this.refreshMeeting(id)
        return analysis
      } catch (error) { this.error = messageFor(error, '保存分析结果失败'); throw error }
    },
    async deleteMeeting(id: string) {
      await meetingApi.deleteMeeting(id)
      this.meetings = this.meetings.filter((item) => item.id !== id)
      if (this.current?.id === id) this.current = null
    },
  },
})
