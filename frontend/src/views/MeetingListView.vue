<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Delete, Document, Plus, Right } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useMeetingStore } from '@/stores/meetingStore'
import MeetingStatusTag from '@/components/MeetingStatusTag.vue'
import { formatDate, formatDuration, formatBytes } from '@/utils/format'

const router = useRouter(); const store = useMeetingStore(); const deleting = ref('')
onMounted(() => store.fetchMeetings())
async function remove(id: string, title: string) { try { await ElMessageBox.confirm(`确认永久删除“${title}”？会议音频、转录和分析数据将从本机清除。`, '删除会议', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }); deleting.value = id; await store.deleteMeeting(id); ElMessage.success('会议已删除') } catch { /* cancelled */ } finally { deleting.value = '' } }
</script>
<template>
  <div class="page-heading"><div><h1>会议记录</h1><p>集中查看录音处理进度和结构化会议结果。</p></div><el-button type="primary" :icon="Plus" @click="router.push('/meetings/new')">新建会议</el-button></div>
  <el-alert v-if="store.error" :title="store.error" type="error" show-icon closable class="mb16" />
  <div v-loading="store.loading" class="grid meeting-grid">
    <div v-if="!store.loading && !store.meetings.length" class="card empty-card"><el-icon :size="40" color="#8b94a7"><Document /></el-icon><h3>还没有会议记录</h3><p>上传一次会议录音，开始生成你的第一份会议纪要。</p><el-button type="primary" @click="router.push('/meetings/new')">创建第一条会议</el-button></div>
    <div v-for="meeting in store.meetings" :key="meeting.id" class="card meeting-card" @click="router.push(`/meetings/${meeting.id}`)">
      <div class="meeting-card-top"><div class="file-icon"><el-icon><Document /></el-icon></div><MeetingStatusTag :status="meeting.status" /></div>
      <h3>{{ meeting.title }}</h3><p class="meeting-context">{{ meeting.analysis?.summary || meeting.context || '等待处理结果…' }}</p>
      <div class="meeting-meta"><span>{{ formatDate(meeting.meetingStartedAt) }}</span><span>{{ formatDuration(meeting.durationMs) }}</span><span>{{ formatBytes(meeting.fileSize) }}</span></div>
      <div class="meeting-footer"><span class="meeting-filename" :title="meeting.originalFilename">{{ meeting.originalFilename }}</span><div class="meeting-actions"><el-button text type="danger" :loading="deleting === meeting.id" :icon="Delete" @click.stop="remove(meeting.id, meeting.title)">删除</el-button><el-button text :icon="Right" @click.stop="router.push(`/meetings/${meeting.id}`)">查看</el-button></div></div>
    </div>
  </div>
</template>
<style scoped>
.mb16 { margin-bottom: 16px; }.meeting-grid { grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }.meeting-card { padding: 20px; cursor: pointer; transition: transform .18s, box-shadow .18s; }.meeting-card:hover { transform: translateY(-2px); box-shadow: 0 12px 32px rgba(37,50,85,.10); }.meeting-card-top { display:flex; align-items:center; justify-content:space-between; }.file-icon { width:38px; height:38px; display:grid; place-items:center; color:#4f46e5; background:#eef0ff; border-radius:11px; }.meeting-card h3 { margin:18px 0 8px; font-size:18px; }.meeting-context { color:var(--mm-muted); line-height:1.6; min-height:51px; margin:0; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }.meeting-meta { display:flex; gap:12px; color:var(--mm-muted); font-size:12px; padding:16px 0; border-bottom:1px solid var(--mm-border); }.meeting-footer { display:flex; align-items:stretch; justify-content:space-between; gap:12px; color:var(--mm-muted); font-size:12px; padding-top:11px; min-height:70px; } .meeting-filename { min-width:0; flex:1; align-self:center; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; line-height:1.5; } .meeting-actions { flex:0 0 72px; display:flex; flex-direction:column; align-items:flex-end; justify-content:center; gap:2px; } .meeting-actions :deep(.el-button) { min-width:64px; justify-content:flex-start; margin-left:0; }.empty-card { padding:80px 20px; text-align:center; grid-column:1/-1; }.empty-card h3 { margin:18px 0 8px; }.empty-card p { color:var(--mm-muted); margin-bottom:22px; }
</style>

