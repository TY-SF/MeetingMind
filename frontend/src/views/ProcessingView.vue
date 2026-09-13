<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CircleCheck, Loading, WarningFilled, ArrowLeft, Document } from '@element-plus/icons-vue'
import { useMeetingStore } from '@/stores/meetingStore'
import { meetingApi } from '@/api/api'
import { formatDate } from '@/utils/format'
import StageDurationList from '@/components/StageDurationList.vue'
import type { JobStage } from '@/types/domain'
import ProcessingTimeline from '@/components/ProcessingTimeline.vue'

const route = useRoute(); const router = useRouter(); const store = useMeetingStore(); const job = ref(store.current?.job || null); const retrying = ref(false); const queueHealth = ref<{ workerOnline: boolean; workerCount: number; queueLength: number } | null>(null); let timer: number | undefined; let queueTimer: number | undefined
const isDone = computed(() => job.value?.stage === 'SUCCEEDED' || job.value?.stage === 'FAILED')
const transcriptionFinished = computed(() => job.value?.stage === 'SUCCEEDED' || Boolean(store.current?.transcript.length))
const aiAnalysisFinished = computed(() => Boolean(store.current?.analysis))
const queueWarning = computed(() => job.value?.stage === 'QUEUED' && queueHealth.value && !queueHealth.value.workerOnline)
const preprocessingStatus = computed(() => {
  if (job.value?.stage === 'FAILED' && !store.current?.transcript.length) return 'error'
  return job.value?.stage === 'QUEUED' ? 'wait' : 'success'
})
const transcriptionStatus = computed(() => {
  if (transcriptionFinished.value) return 'success'
  if (job.value?.stage === 'FAILED') return 'error'
  return job.value?.stage === 'TRANSCRIBING' ? 'process' : 'wait'
})
const diarizationStatus = computed(() => {
  if (job.value?.stage === 'DIARIZING') return 'process'
  if (job.value?.diarizationStatus === 'SUCCEEDED') return 'success'
  if (job.value?.diarizationStatus === 'DEGRADED') return 'error'
  if (job.value?.diarizationStatus === 'DISABLED') return 'wait'
  return 'wait'
})
const diarizationDescription = computed(() => {
  if (job.value?.stage === 'DIARIZING') return '正在识别并分配说话人标签'
  if (job.value?.diarizationStatus === 'SUCCEEDED') return `已完成，识别到 ${job.value.speakerCount} 位说话人`
  if (job.value?.diarizationStatus === 'DEGRADED') return '未能完成，已保留转录并使用默认标签'
  if (job.value?.diarizationStatus === 'DISABLED') return '当前配置已禁用自动说话人分离'
  return '等待转录完成后执行'
})
async function poll() { try { const meeting = await store.refreshMeeting(route.params.id as string); job.value = meeting.job; if (meeting.job && ['SUCCEEDED', 'FAILED'].includes(meeting.job.stage)) window.clearInterval(timer) } catch { window.clearInterval(timer) } }
async function pollQueueHealth() { try { const health = await meetingApi.getQueueHealth(); queueHealth.value = health } catch { queueHealth.value = { workerOnline: false, workerCount: 0, queueLength: 0 } } }
async function retryJob() {
  if (!job.value) return
  retrying.value = true
  try {
    job.value = await store.retryProcessingJob(job.value.id)
    await pollQueueHealth()
    if (!timer) timer = window.setInterval(poll, 800)
  } finally { retrying.value = false }
}
onMounted(async () => { await poll(); await pollQueueHealth(); if (!isDone.value) timer = window.setInterval(poll, 800); queueTimer = window.setInterval(pollQueueHealth, 5000) })
onBeforeUnmount(() => { window.clearInterval(timer); window.clearInterval(queueTimer) })
</script>
<template>
  <div v-if="job" class="processing-wrap">
    <div class="page-heading"><div><el-button text :icon="ArrowLeft" @click="router.push('/meetings')">返回会议列表</el-button><h1>正在处理会议</h1><p>系统会依次完成音频预处理、转录、说话人分离和 AI 整理。</p></div></div>
    <div class="card processing-card"><div class="processing-header"><div><h2>{{ store.current?.title || '会议录音' }}</h2><p>{{ store.current?.originalFilename }} · 创建于 {{ formatDate(store.current?.createdAt || new Date().toISOString()) }}</p></div><el-progress type="circle" :percentage="job.progress" :width="92" :status="job.stage === 'FAILED' ? 'exception' : job.stage === 'SUCCEEDED' ? 'success' : undefined" /></div>
      <el-alert v-if="job.warning" :title="job.warning" type="warning" show-icon :closable="false" class="mb20" />
      <el-alert v-if="queueWarning" type="warning" show-icon :closable="false" class="mb20">
        <template #title>未检测到在线 RQ Worker，请启动 <code>scripts/start_rq_worker.ps1</code>；长时间无 Worker 时，任务会标记为中断并可重新处理。</template>
      </el-alert>
      <el-alert v-if="job.error" type="error" show-icon :closable="false" class="mb20">
        <template #title>{{ job.errorCode ? `[${job.errorCode}] ` : '' }}{{ job.error }}</template>
      </el-alert>
      <el-alert v-if="job.retryCount > 0" :title="`该任务已自动恢复 ${job.retryCount} 次`" type="info" show-icon :closable="false" class="mb20" />
      <div class="current-stage"><el-icon v-if="!isDone" class="spin"><Loading /></el-icon><el-icon v-else-if="job.stage === 'SUCCEEDED'" color="#67c23a"><CircleCheck /></el-icon><el-icon v-else color="#f56c6c"><WarningFilled /></el-icon><div><strong><ProcessingTimeline :stage="job.stage" /></strong><span>{{ job.message }}</span></div></div>
      <StageDurationList :events="job.stageEvents" class="stage-timings" />
      <el-steps direction="vertical" class="steps">
        <el-step title="预处理" description="验证格式并规范化音频" :status="preprocessingStatus" />
        <el-step title="语音转录" description="生成带时间戳的文本" :status="transcriptionStatus" />
        <el-step title="说话人分离" :description="diarizationDescription" :status="diarizationStatus" />
        <el-step title="AI 整理" :description="aiAnalysisFinished ? '已生成摘要、结论和待办' : '转录完成后可在会议结果页生成'" :status="aiAnalysisFinished ? 'success' : 'wait'" />
      </el-steps>
      <div class="processing-actions"><el-button @click="router.push('/meetings')">{{ isDone ? '返回会议列表' : '后台运行' }}</el-button><el-button v-if="job.stage === 'FAILED'" type="primary" :loading="retrying" @click="retryJob">重新处理</el-button><el-button v-if="job.stage === 'SUCCEEDED'" type="primary" :icon="Document" @click="router.replace(`/meetings/${route.params.id}`)">查看会议结果</el-button></div>
    </div>
  </div>
</template>
<style scoped>
.processing-wrap{max-width:900px;margin:0 auto}.processing-card{padding:30px;}.processing-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:28px}.processing-header h2{margin:0 0 8px;font-size:22px}.processing-header p{margin:0;color:var(--mm-muted)}.current-stage{display:flex;align-items:center;gap:14px;padding:18px;background:#f7f8fc;border-radius:12px;margin-bottom:28px}.current-stage strong{display:block;font-size:16px}.current-stage span{display:block;color:var(--mm-muted);margin-top:5px}.spin{animation:spin 1.2s linear infinite;color:#4f46e5}.steps{max-width:500px;margin:0 auto 20px}.stage-timings{margin-bottom:24px}.processing-actions{display:flex;justify-content:flex-end;gap:12px;padding-top:22px;border-top:1px solid var(--mm-border)}.mb20{margin-bottom:20px}@keyframes spin{to{transform:rotate(360deg)}}
</style>
