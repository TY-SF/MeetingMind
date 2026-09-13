<script setup lang="ts">
import type { JobStage } from '@/types/domain'
defineProps<{ stage: JobStage }>()
const labels: Record<JobStage, string> = { QUEUED: '已排队', PREPROCESSING: '预处理', TRANSCRIBING: '语音转录', ALIGNING: '时间对齐', DIARIZING: '说话人分离', ANALYZING: 'AI 整理', SUCCEEDED: '处理完成', FAILED: '处理失败' }
</script>
<template><span>{{ labels[stage] }}</span></template>
