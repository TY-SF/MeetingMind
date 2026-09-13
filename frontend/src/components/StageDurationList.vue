<script setup lang="ts">
import { formatStageDuration } from '@/utils/format'
import type { JobStage, ProcessingStageEvent, StageEventOutcome } from '@/types/domain'

defineProps<{ events: ProcessingStageEvent[] }>()

const stageLabels: Record<JobStage, string> = {
  QUEUED: '排队等待',
  PREPROCESSING: '音频预处理',
  TRANSCRIBING: '语音转录',
  ALIGNING: '时间对齐',
  DIARIZING: '说话人分离',
  ANALYZING: 'AI 整理',
  SUCCEEDED: '处理完成',
  FAILED: '处理失败',
}
const outcomeLabels: Record<StageEventOutcome, string> = {
  RUNNING: '进行中',
  COMPLETED: '已完成',
  FAILED: '失败',
  INTERRUPTED: '被中断',
}
const outcomeTypes: Record<StageEventOutcome, 'success' | 'warning' | 'danger' | 'primary'> = {
  RUNNING: 'primary',
  COMPLETED: 'success',
  FAILED: 'danger',
  INTERRUPTED: 'warning',
}
</script>

<template>
  <section class="stage-duration-list">
    <div class="stage-duration-heading">
      <div>
        <h3>阶段耗时</h3>
        <small>时间来自后端持久化的真实阶段边界；旧任务不会根据更新时间推算历史。</small>
      </div>
    </div>
    <div v-if="events.length" class="stage-duration-rows">
      <div v-for="event in events" :key="event.id" class="stage-duration-row">
        <div>
          <strong>{{ stageLabels[event.stage] }}</strong>
          <small>{{ event.attempt ? `自动恢复第 ${event.attempt} 次` : '首次执行' }}</small>
        </div>
        <span class="stage-duration-value">{{ formatStageDuration(event.durationMs) }}</span>
        <el-tag size="small" :type="outcomeTypes[event.outcome]">{{ outcomeLabels[event.outcome] }}</el-tag>
      </div>
    </div>
    <el-empty v-else :image-size="54" description="该任务暂无可验证的阶段耗时记录" />
  </section>
</template>

<style scoped>
.stage-duration-heading{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}.stage-duration-heading h3{margin:0 0 5px;font-size:15px}.stage-duration-heading small{color:var(--mm-muted);line-height:1.5}.stage-duration-rows{border:1px solid var(--mm-border);border-radius:10px;overflow:hidden}.stage-duration-row{display:grid;grid-template-columns:minmax(0,1fr) 110px 72px;gap:12px;align-items:center;padding:12px 14px;border-bottom:1px solid var(--mm-border)}.stage-duration-row:last-child{border-bottom:0}.stage-duration-row strong,.stage-duration-row small{display:block}.stage-duration-row small{margin-top:4px;color:var(--mm-muted);font-size:11px}.stage-duration-value{font-variant-numeric:tabular-nums;color:#3f4b60;text-align:right}@media(max-width:600px){.stage-duration-row{grid-template-columns:minmax(0,1fr) auto}.stage-duration-row .el-tag{grid-column:2}.stage-duration-value{grid-column:2;grid-row:1}}
</style>
