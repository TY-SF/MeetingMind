<script setup lang="ts">
import type { MeetingStatus } from '@/types/domain'
import { statusLabel, statusType } from '@/utils/status'
defineProps<{ status: MeetingStatus }>()
</script>
<template><el-tag :type="statusType[status]" effect="light" round>{{ statusLabel[status] }}</el-tag></template>
