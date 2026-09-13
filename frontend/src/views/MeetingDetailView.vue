<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Download, EditPen, Delete, Clock, User, DocumentCopy, MagicStick } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useMeetingStore } from '@/stores/meetingStore'
import { meetingApi } from '@/api/api'
import MeetingStatusTag from '@/components/MeetingStatusTag.vue'
import { formatDate, formatTimestamp, formatDuration } from '@/utils/format'
import StageDurationList from '@/components/StageDurationList.vue'
import type { ActionItem, ActionItemStatus, AnalysisAudit, Decision, DecisionStatus, MeetingAnalysis } from '@/types/domain'

const route = useRoute()
const router = useRouter()
const store = useMeetingStore()
const activeTab = ref('overview')
const saving = ref(false)
const speakerSaving = ref(false)
const speakerEditing = ref(false)
const speakerDraft = ref<Record<string, string>>({})
const generating = ref(false)
const editing = ref(false)
const audit = ref<AnalysisAudit | null>(null)
const auditLoading = ref(false)

function emptyDraft(): MeetingAnalysis {
  return { summary: '', decisions: [], actionItems: [], version: 1, provider: null, model: null, promptVersion: null }
}

const draft = ref<MeetingAnalysis>(emptyDraft())
const meeting = computed(() => store.current)
const analysis = computed(() => meeting.value?.analysis ?? null)
const canGenerateAnalysis = computed(() => Boolean(meeting.value?.transcript.length) && !analysis.value)
const decisionStatuses: DecisionStatus[] = ['CONFIRMED', 'PROPOSED', 'DISPUTED', 'UNRESOLVED']
const actionStatuses: ActionItemStatus[] = ['TODO', 'IN_PROGRESS', 'DONE', 'CANCELLED']

onMounted(async () => {
  try {
    await store.fetchMeeting(route.params.id as string)
    syncDraft()
    syncSpeakerDraft()
    await loadAudit()
  } catch {
    ElMessage.error(store.error || '加载会议失败')
    router.replace('/meetings')
  }
})

async function loadAudit() {
  if (!meeting.value?.analysis) { audit.value = null; return }
  auditLoading.value = true
  try {
    audit.value = await meetingApi.getAnalysisAudit(meeting.value.id)
  } catch {
    audit.value = null
  } finally {
    auditLoading.value = false
  }
}

function syncDraft() {
  draft.value = analysis.value ? JSON.parse(JSON.stringify(analysis.value)) as MeetingAnalysis : emptyDraft()
}

function beginEditing() {
  if (!analysis.value) return
  syncDraft()
  editing.value = true
}

function syncSpeakerDraft() {
  if (!meeting.value) return
  const labels = new Set(meeting.value.transcript.map((item) => item.speakerLabel))
  speakerDraft.value = Object.fromEntries([...labels].map((label) => [
    label,
    meeting.value?.transcript.find((item) => item.speakerLabel === label)?.speaker || label,
  ]))
}

function beginSpeakerEditing() {
  syncSpeakerDraft()
  speakerEditing.value = true
}

async function saveSpeakerMappings() {
  if (!meeting.value) return
  const mappings = Object.entries(speakerDraft.value)
    .map(([speakerLabel, speakerName]) => ({ speakerLabel, speakerName: speakerName.trim() }))
    .filter((item) => item.speakerName && item.speakerName !== item.speakerLabel)
  if (!mappings.length) {
    ElMessage.warning('请至少填写一个新的说话人姓名')
    return
  }
  speakerSaving.value = true
  try {
    await store.updateSpeakers(meeting.value.id, mappings)
    syncSpeakerDraft()
    speakerEditing.value = false
    ElMessage.success('说话人姓名已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存说话人映射失败')
  } finally {
    speakerSaving.value = false
  }
}

function addAction() {
  draft.value.actionItems.push({
    id: `new-${Date.now()}`,
    content: '',
    assignee: null,
    assigneeStatus: 'UNKNOWN',
    dueDateRaw: null,
    dueAt: null,
    duePrecision: null,
    dueDateStatus: 'UNKNOWN',
    status: 'TODO',
    evidenceText: null,
    evidenceStartMs: null,
  })
}

function removeAction(index: number) { draft.value.actionItems.splice(index, 1) }

function addDecision() {
  draft.value.decisions.push({
    id: `new-${Date.now()}`,
    content: '',
    status: 'CONFIRMED',
    evidenceText: null,
    evidenceStartMs: null,
  })
}

function removeDecision(index: number) { draft.value.decisions.splice(index, 1) }

function markDueDateChanged(item: ActionItem) {
  item.dueAt = null
  item.duePrecision = null
  item.dueDateStatus = item.dueDateRaw?.trim() ? 'AMBIGUOUS' : 'UNKNOWN'
}

function validateDraft() {
  if (!draft.value.summary.trim()) return '会议摘要不能为空'
  if (draft.value.decisions.some((item) => !item.content.trim())) return '结论内容不能为空'
  if (draft.value.actionItems.some((item) => !item.content.trim())) return '待办内容不能为空'
  return ''
}

async function generateAnalysis() {
  if (!meeting.value) return
  if (analysis.value) {
    try {
      await ElMessageBox.confirm(
        '重新生成会用新的 AI 草稿替换当前摘要、结论和待办；原始 AI 响应快照会更新。是否继续？',
        '重新生成 AI 草稿',
        { type: 'warning', confirmButtonText: '继续生成', cancelButtonText: '取消' },
      )
    } catch { return }
  }
  generating.value = true
  try {
    await store.generateAnalysis(meeting.value.id)
    syncDraft()
    editing.value = false
    await loadAudit()
    ElMessage.success('AI 分析已生成，请审核后再保存修改')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '生成 AI 分析失败')
  } finally {
    generating.value = false
  }
}

async function save() {
  if (!meeting.value) return
  const validationError = validateDraft()
  if (validationError) { ElMessage.warning(validationError); return }
  saving.value = true
  try {
    await store.updateAnalysis(meeting.value.id, draft.value)
    syncDraft()
    editing.value = false
    await loadAudit()
    ElMessage.success('人工审核结果已保存')
  } catch (error) {
    if ((error instanceof Error ? error.message : '').includes('分析版本已变更')) {
      await store.fetchMeeting(meeting.value.id)
      syncDraft()
      editing.value = false
      ElMessage.warning('分析结果已被更新，已重新加载最新版本，请确认后再编辑。')
      return
    }
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function exportMarkdown() {
  if (!meeting.value || !analysis.value) { ElMessage.warning('请先生成 AI 分析后再导出'); return }
  try {
    await meetingApi.downloadMarkdown(meeting.value.id)
    ElMessage.success('Markdown 已下载')
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : 'Markdown 导出失败') }
}

async function exportCalendar() {
  if (!meeting.value || !analysis.value) { ElMessage.warning('请先生成 AI 分析后再导出'); return }
  try {
    await meetingApi.downloadCalendar(meeting.value.id)
    ElMessage.success('ICS 日历已下载')
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : 'ICS 导出失败') }
}

async function remove() {
  if (!meeting.value) return
  try {
    await ElMessageBox.confirm('删除后，会议音频、转录和分析数据将无法恢复，确认继续？', '永久删除', {
      type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消',
    })
    await store.deleteMeeting(meeting.value.id)
    ElMessage.success('会议已删除')
    router.replace('/meetings')
  } catch { /* User cancelled the dialog. */ }
}
</script>

<template>
  <div v-if="meeting">
    <div class="page-heading">
      <div>
        <el-button text :icon="ArrowLeft" @click="router.push('/meetings')">返回会议列表</el-button>
        <div class="title-row"><h1>{{ meeting.title }}</h1><MeetingStatusTag :status="meeting.status" /></div>
        <p>{{ meeting.originalFilename }} · {{ formatDate(meeting.meetingStartedAt) }} · {{ formatDuration(meeting.durationMs) }}</p>
      </div>
      <div class="heading-actions">
        <el-dropdown split-button type="primary" :icon="Download" :disabled="!analysis" @click="exportMarkdown">
          导出 Markdown
          <template #dropdown><el-dropdown-menu><el-dropdown-item @click="exportMarkdown">导出 Markdown</el-dropdown-item><el-dropdown-item @click="exportCalendar">导出 ICS 日历</el-dropdown-item></el-dropdown-menu></template>
        </el-dropdown>
        <el-button type="danger" plain :icon="Delete" @click="remove">删除</el-button>
      </div>
    </div>

    <el-alert v-if="store.error" :title="store.error" type="error" show-icon closable class="mb18" />
    <el-alert v-if="meeting.job?.warning" :title="meeting.job.warning" type="warning" show-icon :closable="false" class="mb18" />

    <el-alert v-if="!analysis" type="info" show-icon :closable="false" class="mb18">
      <template #title>转录已准备好后，可生成 AI 分析草稿</template>
      <template #default>系统只会把带时间戳的转录文本发送到已配置的模型服务；原始音频不会发送。生成结果可在本页人工审核和保存。</template>
    </el-alert>

    <div v-if="!analysis" class="analysis-empty card">
      <el-empty :description="meeting.transcript.length ? '尚未生成 AI 分析草稿' : '会议转录尚未完成'">
        <el-button v-if="canGenerateAnalysis" type="primary" :icon="MagicStick" :loading="generating" @click="generateAnalysis">生成 AI 分析</el-button>
        <el-button v-else-if="meeting.status === 'PROCESSING'" @click="router.replace(`/meetings/${meeting.id}/processing`)">查看处理进度</el-button>
      </el-empty>
    </div>

    <template v-else>
      <div class="analysis-toolbar">
        <el-button type="primary" plain :icon="MagicStick" :loading="generating" @click="generateAnalysis">重新生成 AI 草稿</el-button>
        <span>当前版本 {{ analysis.version }} · {{ analysis.provider || '人工' }} · {{ analysis.model || '未记录模型' }}</span>
      </div>

      <el-tabs v-model="activeTab" class="detail-tabs">
        <el-tab-pane label="概览" name="overview">
          <div class="two-col grid">
            <div class="card panel">
              <div class="panel-title"><h2>会议摘要</h2><el-button v-if="!editing" text type="primary" :icon="EditPen" @click="beginEditing">编辑</el-button></div>
              <el-input v-if="editing" v-model="draft.summary" type="textarea" :rows="5" maxlength="5000" show-word-limit />
              <p v-else class="summary-text">{{ analysis.summary }}</p>
              <div class="stats">
                <div><span>参会人</span><strong>{{ meeting.participants.length ? meeting.participants.join('、') : '未填写' }}</strong></div>
                <div><span>处理方式</span><strong>本地转录 + AI 整理</strong></div>
              </div>
            </div>
            <div class="card panel">
              <h2>会议信息</h2>
              <div class="info-line"><el-icon><Clock /></el-icon><span>会议时间</span><strong>{{ formatDate(meeting.meetingStartedAt) }}</strong></div>
              <div class="info-line"><el-icon><DocumentCopy /></el-icon><span>音频文件</span><strong class="info-value-file" :title="meeting.originalFilename">{{ meeting.originalFilename }}</strong></div>
              <div class="info-line"><el-icon><User /></el-icon><span>文件大小</span><strong>{{ (meeting.fileSize / 1024 / 1024).toFixed(1) }} MB</strong></div>
              <div v-if="meeting.context" class="context"><span>会议背景</span><p>{{ meeting.context }}</p></div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="关键结论" name="decisions">
          <div class="card panel">
            <div class="panel-title"><h2>会议结论</h2><el-button v-if="editing" text type="primary" @click="addDecision">添加结论</el-button><el-button v-else text type="primary" :icon="EditPen" @click="beginEditing">编辑</el-button></div>
            <div v-if="draft.decisions.length" class="editable-list">
              <div v-for="(decision, index) in draft.decisions" :key="decision.id" class="list-row">
                <template v-if="editing">
                  <el-input v-model="decision.content" type="textarea" :rows="2" maxlength="2000" />
                  <div class="row-controls"><el-select v-model="decision.status" style="width: 160px"><el-option v-for="status in decisionStatuses" :key="status" :label="status" :value="status" /></el-select><el-button text type="danger" @click="removeDecision(index)">删除</el-button></div>
                </template>
                <template v-else><el-tag>{{ decision.status }}</el-tag><p>{{ decision.content }}</p><small>证据：{{ decision.evidenceText || '暂无' }}</small></template>
              </div>
            </div>
            <el-empty v-else description="暂无关键结论" />
          </div>
        </el-tab-pane>

        <el-tab-pane label="待办事项" name="actions">
          <div class="card panel">
            <div class="panel-title"><h2>行动项</h2><el-button v-if="editing" text type="primary" @click="addAction">添加待办</el-button><el-button v-else text type="primary" :icon="EditPen" @click="beginEditing">编辑</el-button></div>
            <div v-if="draft.actionItems.length" class="action-list">
              <div v-for="(item, index) in draft.actionItems" :key="item.id" class="action-row">
                <template v-if="editing">
                  <el-input v-model="item.content" placeholder="待办内容" maxlength="2000" />
                  <div class="row-controls">
                    <el-input v-model="item.assignee" placeholder="负责人" style="width: 160px" />
                    <el-input v-model="item.dueDateRaw" placeholder="截止时间原文" style="width: 160px" @input="markDueDateChanged(item)" />
                    <el-select v-model="item.status" style="width: 145px"><el-option v-for="status in actionStatuses" :key="status" :label="status" :value="status" /></el-select>
                    <el-button text type="danger" @click="removeAction(index)">删除</el-button>
                  </div>
                  <small v-if="item.dueDateStatus === 'AMBIGUOUS'">截止日期文本已修改，等待人工确认，未保留旧的标准化日期。</small>
                </template>
                <template v-else>
                  <div><strong>{{ item.content }}</strong><p>{{ item.evidenceText || '暂无原文证据' }}</p></div>
                  <div class="action-meta"><span>{{ item.assignee || '未指定负责人' }}</span><span>{{ item.dueDateRaw || '未指定截止时间' }}</span><el-tag size="small">{{ item.status }}</el-tag></div>
                </template>
              </div>
            </div>
            <el-empty v-else description="暂无待办事项" />
          </div>
        </el-tab-pane>

        <el-tab-pane label="完整转录" name="transcript">
          <div class="card panel">
            <div class="panel-title"><div><h2>带时间戳的转录</h2><small class="panel-hint">原始标签保留不变，可映射为真实姓名</small></div><el-button v-if="meeting.transcript.length && !speakerEditing" text type="primary" :icon="EditPen" @click="beginSpeakerEditing">编辑说话人</el-button></div>
            <div v-if="speakerEditing" class="speaker-editor">
              <div v-for="(name, label) in speakerDraft" :key="label" class="speaker-edit-row"><span>{{ label }}</span><el-input v-model="speakerDraft[label]" :placeholder="label" /></div>
              <div class="speaker-actions"><el-button @click="speakerEditing = false; syncSpeakerDraft()">取消</el-button><el-button type="primary" :loading="speakerSaving" @click="saveSpeakerMappings">保存映射</el-button></div>
            </div>
            <div v-if="meeting.transcript.length" class="transcript-list">
              <div v-for="item in meeting.transcript" :key="item.id" class="transcript-item"><span class="timestamp">{{ formatTimestamp(item.startMs) }}</span><strong>{{ item.speaker }}</strong><p>{{ item.text }}</p></div>
            </div>
            <el-empty v-else description="暂无转录内容" />
          </div>
        </el-tab-pane>

        <el-tab-pane label="处理信息" name="processing">
          <div class="card panel">
            <div class="info-line processing-info-line"><span>处理状态</span><strong>{{ meeting.status }}</strong></div>
            <div class="info-line processing-info-line"><span>任务阶段</span><strong>{{ meeting.job?.stage || '无' }}</strong></div>
            <div class="info-line processing-info-line"><span>自动恢复次数</span><strong>{{ meeting.job?.retryCount || 0 }}</strong></div>
            <div class="info-line processing-info-line"><span>错误码</span><strong>{{ meeting.job?.errorCode || '无' }}</strong></div>
            <div class="info-line processing-info-line"><span>AI Provider</span><strong>{{ analysis.provider || '未记录' }}</strong></div>
            <div class="info-line processing-info-line"><span>模型</span><strong>{{ analysis.model || '未记录' }}</strong></div>
            <div class="info-line processing-info-line"><span>Prompt 版本</span><strong>{{ analysis.promptVersion || '未记录' }}</strong></div>
            <div class="info-line processing-info-line"><span>分析版本</span><strong>{{ analysis.version }}</strong></div>
          </div>
          <div class="card panel audit-panel"><StageDurationList :events="meeting.job?.stageEvents || []" /></div>

          <div v-loading="auditLoading" class="card panel audit-panel">
            <div class="panel-title">
              <div>
                <h2>AI 原始草稿与人工结果</h2>
                <small class="panel-hint">仅展示结构化分析字段，不返回模型服务的完整原始响应。</small>
              </div>
              <el-tag v-if="audit" :type="audit.hasChanges ? 'warning' : 'success'" effect="light">
                {{ audit.hasChanges ? '已人工修改' : '未修改' }}
              </el-tag>
            </div>

            <template v-if="audit?.aiOriginal">
              <div class="audit-changes">
                <span>发生变化的字段</span>
                <template v-if="audit.changedFields.length">
                  <el-tag v-for="field in audit.changedFields" :key="field" size="small" type="warning">{{ field }}</el-tag>
                </template>
                <strong v-else>无</strong>
              </div>
              <div class="audit-grid">
                <section>
                  <h3>AI 原始草稿</h3>
                  <p>{{ audit.aiOriginal.summary || '无摘要' }}</p>
                  <div class="audit-counts">
                    <span>结论 {{ audit.aiOriginal.decisions.length }} 条</span>
                    <span>待办 {{ audit.aiOriginal.actionItems.length }} 条</span>
                  </div>
                </section>
                <section>
                  <h3>当前审核结果</h3>
                  <p>{{ audit.current.summary || '无摘要' }}</p>
                  <div class="audit-counts">
                    <span>结论 {{ audit.current.decisions.length }} 条</span>
                    <span>待办 {{ audit.current.actionItems.length }} 条</span>
                  </div>
                </section>
              </div>
            </template>
            <el-empty v-else-if="!auditLoading" description="当前记录没有可解析的 AI 原始结构化草稿" />
          </div>
        </el-tab-pane>
      </el-tabs>

      <div v-if="editing" class="save-bar"><el-button @click="syncDraft(); editing = false">取消修改</el-button><el-button type="primary" :loading="saving" @click="save">保存当前结果</el-button></div>
    </template>
  </div>
</template>

<style scoped>
.title-row { display:flex; align-items:center; gap:12px; }.title-row h1 { margin:0; }.heading-actions { display:flex; gap:10px; }.detail-tabs { margin-top:5px; }.analysis-empty { min-height:250px; display:grid; place-items:center; }.analysis-toolbar { display:flex; justify-content:space-between; align-items:center; gap:12px; margin:0 0 12px; color:var(--mm-muted); font-size:13px; }.panel { padding:24px; min-height:220px; }.panel h2 { font-size:17px; margin:0; }.panel-title { display:flex; justify-content:space-between; align-items:center; margin-bottom:18px; }.panel-hint { display:block; color:var(--mm-muted); margin-top:5px; font-size:12px; }.speaker-editor { display:grid; gap:10px; padding:14px; margin-bottom:14px; background:#f7f8fc; border-radius:10px; }.speaker-edit-row { display:grid; grid-template-columns:140px minmax(0,1fr); align-items:center; gap:12px; }.speaker-edit-row > span { color:var(--mm-muted); font-family:monospace; }.speaker-actions { display:flex; justify-content:flex-end; gap:8px; margin-top:4px; }.summary-text { line-height:1.8; color:#3f4b60; min-height:70px; white-space:pre-wrap; }.stats { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:22px; }.stats div { background:#f7f8fc; padding:13px; border-radius:10px; }.stats span,.context span { display:block; color:var(--mm-muted); font-size:12px; margin-bottom:6px; }.stats strong { font-size:13px; }.info-line { display:grid; grid-template-columns:20px minmax(70px,max-content) minmax(0,1fr); gap:8px; align-items:center; padding:13px 0; border-bottom:1px solid var(--mm-border); font-size:13px; min-width:0; }.info-line span { color:var(--mm-muted); white-space:nowrap; }.info-line strong { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; text-align:right; }.processing-info-line { grid-template-columns:minmax(100px,max-content) minmax(0,1fr); }.processing-info-line strong { text-align:left; }.info-value-file { display:block; }.context { padding-top:18px; }.context p { line-height:1.6; margin:0; }.transcript-list { display:grid; gap:0; }.transcript-item { display:grid; grid-template-columns:55px 100px 1fr; gap:12px; padding:17px 0; border-bottom:1px solid var(--mm-border); align-items:start; }.transcript-item .timestamp { font-family:monospace; color:#4f46e5; }.transcript-item strong { font-size:13px; }.transcript-item p { margin:0; line-height:1.6; }.list-row,.action-row { border-bottom:1px solid var(--mm-border); padding:15px 0; }.list-row:last-child,.action-row:last-child { border-bottom:0; }.list-row p { margin:10px 0 5px; line-height:1.5; }.list-row small,.action-row p,.action-row small { color:var(--mm-muted); }.row-controls { display:flex; gap:10px; margin-top:10px; align-items:center; flex-wrap:wrap; }.action-row { display:flex; justify-content:space-between; gap:20px; align-items:center; }.action-row strong { font-size:14px; }.action-row p { margin:7px 0 0; font-size:12px; }.action-meta { display:flex; align-items:center; gap:12px; white-space:nowrap; color:var(--mm-muted); font-size:12px; }.save-bar { position:sticky; bottom:18px; display:flex; justify-content:flex-end; gap:10px; background:#fff; border:1px solid var(--mm-border); border-radius:12px; padding:12px; margin-top:18px; box-shadow:0 8px 30px rgba(37,50,85,.12); }.audit-panel { margin-top:16px; }.audit-changes { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:14px; color:var(--mm-muted); font-size:13px; }.audit-changes strong { color:#3f4b60; }.audit-grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:14px; }.audit-grid section { min-width:0; padding:16px; background:#f7f8fc; border-radius:10px; }.audit-grid h3 { margin:0 0 10px; font-size:14px; }.audit-grid p { min-height:72px; margin:0; line-height:1.7; white-space:pre-wrap; overflow-wrap:anywhere; color:#3f4b60; }.audit-counts { display:flex; gap:16px; flex-wrap:wrap; margin-top:14px; color:var(--mm-muted); font-size:12px; }.mb18 { margin-bottom:18px; } @media(max-width:760px) { .heading-actions { width:100%; }.heading-actions .el-button { flex:1; }.analysis-toolbar { align-items:flex-start; flex-direction:column; }.stats,.audit-grid { grid-template-columns:1fr; }.transcript-item { grid-template-columns:50px 1fr; }.transcript-item p { grid-column:2; }.action-row { display:block; }.action-meta { margin-top:12px; flex-wrap:wrap; } }
</style>
