<script setup>
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

const props = defineProps({
  currentSection: { type: String, default: 'project' }
})

const emit = defineEmits(['switch-section', 'logout', 'show-help', 'show-admin-switch', 'show-profile'])
const authStore = useAuthStore()
const isAdmin = computed(() => authStore.isAdmin)
const hasAdminToken = computed(() => !!authStore.adminToken)
</script>

<template>
  <header class="h-14 bg-[#0f172a] text-white flex items-center justify-between px-6 shrink-0 border-b border-slate-800">
    <div class="flex items-center gap-10">
      <div class="flex items-center cursor-pointer">
        <h1 class="text-xl font-bold tracking-wide text-white" style="font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Helvetica Neue', 'Microsoft YaHei', sans-serif;">
          Clarity 澄澈系统
        </h1>
      </div>

      <nav class="flex gap-6 text-sm font-medium text-slate-300">
        <a
          v-if="!isAdmin"
          href="#"
          class="pb-1 -mb-1.5 transition-colors"
          :class="['project', 'history', 'arbitration'].includes(currentSection) ? 'text-white border-b-2 border-blue-500' : 'hover:text-white'"
          @click.prevent="emit('switch-section', 'project')"
        >
          项目大厅
        </a>
        <a
          v-if="isAdmin"
          href="#"
          class="pb-1 -mb-1.5 transition-colors"
          :class="currentSection === 'admin' ? 'text-white border-b-2 border-blue-500' : 'hover:text-white'"
          @click.prevent="emit('switch-section', 'admin')"
        >
          系统管理
        </a>
        <a
          href="#"
          class="pb-1 -mb-1.5 transition-colors"
          :class="currentSection === 'blockchain' ? 'text-white border-b-2 border-blue-500' : 'hover:text-white'"
          @click.prevent="emit('switch-section', 'blockchain')"
        >
          链上查询
        </a>
        <a
          v-if="!isAdmin"
          href="#"
          class="hover:text-white transition-colors"
          @click.prevent="emit('show-help')"
        >
          帮助
        </a>
      </nav>
    </div>

    <div class="flex items-center gap-4">
      <!-- ADMIN 模式标识 -->
      <div
        v-if="isAdmin"
        class="text-[10px] font-bold text-amber-400 bg-amber-400/10 border border-amber-400/30 px-2 py-0.5 rounded-sm tracking-wider uppercase"
      >
        ADMIN 模式
      </div>

      <div
        class="text-sm font-medium hover:text-slate-300 cursor-pointer transition-colors flex items-center gap-2"
        @click="isAdmin || hasAdminToken ? emit('show-admin-switch') : emit('show-profile')"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
        </svg>
        {{ isAdmin || hasAdminToken ? '切换账号' : '个人管理' }}
      </div>
      <div class="h-4 w-px bg-slate-700"></div>
      <div
        class="text-sm font-medium text-slate-400 hover:text-white cursor-pointer transition-colors flex items-center gap-1"
        @click="emit('logout')"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"></path>
        </svg>
        退出登录
      </div>
    </div>
  </header>
</template>
