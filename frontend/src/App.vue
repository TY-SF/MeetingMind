<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, VideoCamera } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const isDetail = computed(() => route.path !== '/meetings')
</script>

<template>
  <el-container class="app-shell">
    <el-header class="app-header">
      <div class="brand" @click="router.push('/meetings')">
        <div class="brand-mark"><el-icon><VideoCamera /></el-icon></div>
        <div><strong>MeetingMind</strong><span>智能会议整理</span></div>
      </div>
      <div class="header-actions">
        <el-button v-if="isDetail" text @click="router.push('/meetings')">会议列表</el-button>
        <el-button type="primary" :icon="Plus" @click="router.push('/meetings/new')">新建会议</el-button>
      </div>
    </el-header>
    <el-main class="app-main"><router-view /></el-main>
  </el-container>
</template>
