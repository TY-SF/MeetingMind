<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UploadFilled, ArrowLeft, Document, Close } from '@element-plus/icons-vue'
import { useMeetingStore } from '@/stores/meetingStore'

const router = useRouter()
const store = useMeetingStore()
const formRef = ref()
const file = ref<File | null>(null)
const submitting = ref(false)
const form = ref({
  title: '',
  meetingStartedAt: new Date().toISOString().slice(0, 16),
  participants: '',
  context: '',
  dataProcessingConfirmed: false,
})
const rules = {
  title: [{ required: true, message: '请输入会议标题', trigger: 'blur' }],
  meetingStartedAt: [{ required: true, message: '请选择会议时间', trigger: 'change' }],
}
const fileError = computed(() => file.value && !['audio/mpeg', 'audio/wav', 'audio/x-wav', 'audio/mp4', 'audio/x-m4a'].includes(file.value.type)
  ? '建议选择 MP3、WAV 或 M4A 音频文件'
  : '')

function chooseFile(uploadFile: { raw?: File }) {
  if (uploadFile.raw) file.value = uploadFile.raw
}

function clearFile(event: MouseEvent) {
  event.stopPropagation()
  file.value = null
}

async function submit() {
  await formRef.value.validate()
  if (!form.value.dataProcessingConfirmed) {
    ElMessage.warning('请先确认录音授权与隐私边界')
    return
  }
  if (!file.value) {
    ElMessage.warning('请先选择一份录音文件')
    return
  }
  if (fileError.value) {
    ElMessage.warning(fileError.value)
    return
  }

  submitting.value = true
  try {
    const meeting = await store.createMeeting({
      title: form.value.title,
      file: file.value,
      meetingStartedAt: new Date(form.value.meetingStartedAt).toISOString(),
      participants: form.value.participants.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean),
      context: form.value.context,
      dataProcessingConfirmed: form.value.dataProcessingConfirmed,
    })
    ElMessage.success('录音已上传，正在开始处理')
    router.replace(`/meetings/${meeting.id}/processing`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '上传失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="page-heading">
    <div>
      <el-button text :icon="ArrowLeft" @click="router.push('/meetings')">返回会议列表</el-button>
      <h1>新建会议</h1>
      <p>录入会议基本信息并上传录音，系统会在后台完成真实处理。</p>
    </div>
  </div>
  <el-card class="form-card" shadow="never">
    <el-alert
      title="隐私边界：原始音频保存在本机并在本机完成转录和说话人分离；只有在你主动点击 AI 分析时，带时间戳的转录文本和会议背景才会发送到已配置的模型服务。系统不会自动脱敏，请仅上传你有权处理的录音。"
      type="warning"
      show-icon
      :closable="false"
      class="mb24"
    />
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
      <div class="form-grid">
        <el-form-item label="会议标题" prop="title">
          <el-input v-model="form.title" placeholder="例如：产品迭代周会" maxlength="80" show-word-limit />
        </el-form-item>
        <el-form-item label="会议发生时间" prop="meetingStartedAt">
          <el-date-picker v-model="form.meetingStartedAt" type="datetime" format="YYYY-MM-DD HH:mm" value-format="YYYY-MM-DDTHH:mm" style="width:100%" />
        </el-form-item>
      </div>
      <el-form-item label="录音文件" required>
        <div class="upload-section">
          <el-upload class="audio-uploader" drag :auto-upload="false" :show-file-list="false" accept=".mp3,.wav,.m4a" :on-change="chooseFile">
            <template v-if="!file">
              <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
              <div class="el-upload__text">将音频拖到此处，或<em>点击选择</em></div>
            </template>
            <div v-else class="selected-file">
              <div class="selected-file-icon"><el-icon><Document /></el-icon></div>
              <div class="selected-file-info">
                <strong :title="file.name">{{ file.name }}</strong>
                <span>{{ (file.size / 1024 / 1024).toFixed(1) }} MB · 已选择</span>
              </div>
              <button type="button" class="remove-file-button" aria-label="移除文件" title="移除文件" @click.stop.prevent="clearFile"><Close /></button>
            </div>
            <template #tip><div class="el-upload__tip">支持 MP3、WAV、M4A；默认文件上限为 200 MB，以后端配置为准。</div></template>
          </el-upload>
          <el-text v-if="fileError" type="warning" class="file-error">{{ fileError }}</el-text>
        </div>
      </el-form-item>
      <el-form-item label="参会人">
        <el-input v-model="form.participants" type="textarea" :rows="2" placeholder="多人可用逗号或换行分隔" />
      </el-form-item>
      <el-form-item label="会议背景">
        <el-input v-model="form.context" type="textarea" :rows="3" maxlength="500" show-word-limit placeholder="可选：补充会议目标、项目背景或术语解释" />
      </el-form-item>
      <el-form-item class="consent-item" required>
        <el-checkbox v-model="form.dataProcessingConfirmed" class="consent-checkbox">
          我确认有权处理该录音，并理解系统不会自动脱敏；只有在我主动点击 AI 分析时，带时间戳的转录文本和会议背景才会发送到已配置的模型服务，原始音频不会发送。
        </el-checkbox>
      </el-form-item>
      <div class="form-actions">
        <el-button @click="router.push('/meetings')">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">创建并开始处理</el-button>
      </div>
    </el-form>
  </el-card>
</template>
<style scoped>
.form-card { max-width: 860px; margin: 0 auto; border-radius:16px; }.mb24 { margin-bottom:24px; }.form-grid { display:grid; grid-template-columns:1fr 1fr; gap:18px; }.upload-section { width:100%; } .audio-uploader { width:100%; } .audio-uploader :deep(.el-upload) { display:block; width:100%; } .audio-uploader :deep(.el-upload-dragger) { width:100%; min-height:180px; display:flex; align-items:center; justify-content:center; padding:28px; border-radius:12px; transition:all .2s; } .audio-uploader :deep(.el-upload-dragger:hover) { border-color:var(--mm-primary); background:#fafaff; } .selected-file { width:100%; min-height:110px; display:flex; align-items:center; gap:14px; text-align:left; padding:20px 22px; border:1px solid #d9ddff; border-radius:10px; background:linear-gradient(135deg,#f7f7ff,#f0f2ff); color:var(--mm-ink); } .selected-file-icon { width:42px; height:42px; flex:0 0 42px; display:grid; place-items:center; border-radius:11px; color:var(--mm-primary); background:#e4e6ff; font-size:20px; } .selected-file-info { min-width:0; flex:1; } .remove-file-button { width:34px; height:34px; flex:0 0 34px; display:grid; place-items:center; padding:0; border:1px solid #fbc4c4; border-radius:8px; color:#f56c6c; background:#fff; cursor:pointer; transition:all .18s; } .remove-file-button:hover { color:#fff; border-color:#f56c6c; background:#f56c6c; } .selected-file-info strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:14px; } .selected-file-info span { display:block; margin-top:5px; color:var(--mm-muted); font-size:12px; } .file-error { display:block; margin-top:8px; }.consent-item :deep(.el-form-item__content) { line-height:1.6; } .consent-checkbox { align-items:flex-start; white-space:normal; } .consent-checkbox :deep(.el-checkbox__input) { margin-top:4px; } .form-actions { display:flex; justify-content:flex-end; gap:12px; margin-top:28px; padding-top:20px; border-top:1px solid var(--mm-border); }@media(max-width:650px){.form-grid{grid-template-columns:1fr;}}
</style>


