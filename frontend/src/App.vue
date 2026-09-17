<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Lock, Plus, VideoCamera } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ACCESS_TOKEN_REQUIRED_EVENT, hasAccessToken, setAccessToken } from '@/api/accessToken'

const route = useRoute()
const router = useRouter()
const isDetail = computed(() => route.path !== '/meetings')
const tokenConfigured = ref(hasAccessToken())
let prompting = false

async function promptForAccessToken(invalid = false) {
  if (prompting) return
  prompting = true
  try {
    const result = await ElMessageBox.prompt(
      invalid
        ? '当前访问令牌无效或已轮换。请输入后端配置的 MEETINGMIND_API_TOKEN。'
        : '请输入后端配置的 MEETINGMIND_API_TOKEN。令牌只保存在当前浏览器标签页会话中。',
      'MeetingMind 访问令牌',
      {
        inputType: 'password',
        inputPlaceholder: '至少 32 个字符',
        inputValidator: (value) => value.trim().length >= 32 || '访问令牌至少需要 32 个字符',
        confirmButtonText: '保存并重新连接',
        cancelButtonText: '取消',
        closeOnClickModal: false,
      },
    )
    setAccessToken(result.value)
    tokenConfigured.value = true
    ElMessage.success('访问令牌已保存到当前会话')
    window.location.reload()
  } catch {
    // The user can reopen the prompt from the header without losing local data.
  } finally {
    prompting = false
  }
}

function handleAccessTokenRequired(event: Event) {
  const detail = (event as CustomEvent<{ invalid?: boolean }>).detail
  void promptForAccessToken(Boolean(detail?.invalid))
}

onMounted(() => window.addEventListener(ACCESS_TOKEN_REQUIRED_EVENT, handleAccessTokenRequired))
onUnmounted(() => window.removeEventListener(ACCESS_TOKEN_REQUIRED_EVENT, handleAccessTokenRequired))
</script>

<template>
  <el-container class="app-shell">
    <el-header class="app-header">
      <div class="brand" @click="router.push('/meetings')">
        <div class="brand-mark"><el-icon><VideoCamera /></el-icon></div>
        <div><strong>MeetingMind</strong><span>智能会议整理</span></div>
      </div>
      <div class="header-actions">
        <el-button text :icon="Lock" @click="promptForAccessToken(false)">{{ tokenConfigured ? '更新访问令牌' : '访问令牌' }}</el-button>
        <el-button v-if="isDetail" text @click="router.push('/meetings')">会议列表</el-button>
        <el-button type="primary" :icon="Plus" @click="router.push('/meetings/new')">新建会议</el-button>
      </div>
    </el-header>
    <el-main class="app-main"><router-view /></el-main>
  </el-container>
</template>
