<script setup>
import { onMounted, onBeforeUnmount } from 'vue'
import Toast from '@/components/Toast.vue'
import { useMobileStore } from '@/stores/mobile'

const mobileStore = useMobileStore()

onMounted(() => {
  mobileStore.updateBreakpoint()
  window.addEventListener('resize', mobileStore.updateBreakpoint)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', mobileStore.updateBreakpoint)
})
</script>

<template>
  <router-view />
  <Toast />
</template>
