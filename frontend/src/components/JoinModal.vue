<script setup>
import { ref } from 'vue'

const emit = defineEmits(['close', 'join'])

const projectId = ref('')
const showError = ref(false)
const focused = ref(false)

function handleVerify() {
  if (!projectId.value || projectId.value.trim().length < 5) {
    showError.value = true
    return
  }
  showError.value = false
  emit('join', projectId.value.trim())
}
</script>

<template>
  <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-sm shadow-xl w-full max-w-lg overflow-hidden flex flex-col border border-slate-300">
      <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
        <h2 class="text-sm font-bold text-slate-800">接入新项目</h2>
        <button @click="emit('close')" class="text-slate-400 hover:text-slate-700">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>

      <div class="p-8 space-y-6 bg-white">
        <div class="text-center mb-6">
          <div class="w-12 h-12 bg-slate-100 rounded-sm flex items-center justify-center mx-auto mb-4 border border-slate-200">
            <svg class="w-6 h-6 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"></path>
            </svg>
          </div>
          <p class="text-sm text-slate-600 leading-relaxed">
            请输入制造商提供的专属项目ID。系统校验通过后，将展示该项目的具体验收标准，并开放专属的模型上传入口。
          </p>
        </div>

        <div
          class="border border-slate-300 rounded-sm bg-white transition-all overflow-hidden"
          :class="{ 'shadow-[0_0_0_2px_rgba(15,23,42,0.2)] border-[#0f172a]': focused }"
        >
          <div class="flex items-center px-4 py-3">
            <svg class="w-5 h-5 text-slate-400 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
            </svg>
            <input
              v-model="projectId"
              type="text"
              placeholder="例如：0x2b4C...7a99"
              class="flex-1 text-sm font-mono text-slate-800 focus:outline-none placeholder-slate-400 bg-transparent"
              @focus="focused = true"
              @blur="focused = false"
              @keyup.enter="handleVerify"
            />
          </div>
        </div>

        <div v-if="showError" class="text-xs text-rose-600 font-medium text-center">
          验证码格式错误或在链上未找到对应项目，请核对。
        </div>
      </div>

      <div class="px-6 py-4 border-t border-slate-200 bg-slate-50 flex justify-end gap-3">
        <button
          @click="emit('close')"
          class="px-5 py-2 text-xs font-bold text-slate-600 hover:text-slate-900 bg-white border border-slate-300 rounded-sm"
        >
          取消
        </button>
        <button
          @click="handleVerify"
          class="px-5 py-2 text-xs font-bold text-white bg-[#0f172a] hover:bg-slate-800 rounded-sm"
        >
          校验并接入
        </button>
      </div>
    </div>
  </div>
</template>
