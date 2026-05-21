<script setup>
import { useToastStore } from '@/stores/toast'

const toast = useToastStore()
</script>

<template>
  <div class="fixed top-4 left-1/2 -translate-x-1/2 z-[9999] space-y-2">
    <transition-group name="toast">
      <div
        v-for="msg in toast.messages"
        :key="msg.id"
        class="flex items-stretch min-w-[280px] max-w-[400px] bg-white shadow-lg overflow-hidden"
      >
        <!-- 左侧竖线 -->
        <div
          class="w-1 shrink-0"
          :class="msg.type === 'success' ? 'bg-emerald-500' : 'bg-rose-500'"
        ></div>
        <!-- 内容 -->
        <div class="px-4 py-3 flex-1">
          <p class="text-sm text-slate-800 leading-relaxed">{{ msg.message }}</p>
        </div>
        <!-- 关闭按钮 -->
        <button
          @click="toast.remove(msg.id)"
          class="px-3 py-3 text-slate-400 hover:text-slate-600 transition-colors shrink-0 self-center"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>
    </transition-group>
  </div>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}
.toast-enter-from {
  opacity: 0;
  transform: translateY(-20px);
}
.toast-leave-to {
  opacity: 0;
  transform: translateY(-20px);
}
</style>
