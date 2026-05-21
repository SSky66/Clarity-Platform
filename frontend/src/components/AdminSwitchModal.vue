<script setup>
import { ref, onMounted, computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { listUsers, sudo, getMe } from '@/api/auth'

const toast = useToastStore()
const authStore = useAuthStore()
const emit = defineEmits(['close'])

const users = ref([])
const loading = ref(false)
const searchQuery = ref('')

const roleLabel = {
  MANUFACTURER: '制造商',
  SUPPLIER: '供应商',
  AUDITOR: '审计节点'
}

const roleBadgeClass = {
  MANUFACTURER: 'text-blue-700 bg-blue-50 border-blue-200',
  SUPPLIER: 'text-emerald-700 bg-emerald-50 border-emerald-200',
  AUDITOR: 'text-purple-700 bg-purple-50 border-purple-200'
}

const filteredUsers = computed(() => {
  if (!searchQuery.value.trim()) return users.value
  const q = searchQuery.value.trim().toLowerCase()
  return users.value.filter(u =>
    u.account.toLowerCase().includes(q) ||
    u.display_name.toLowerCase().includes(q) ||
    u.role.toLowerCase().includes(q)
  )
})

async function fetchUsers() {
  loading.value = true
  console.log('fetchUsers - adminToken:', authStore.adminToken?.slice(0, 20) + '...')
  console.log('fetchUsers - current token:', authStore.token?.slice(0, 20) + '...')
  try {
    // 临时用admin_token调接口
    const originalToken = authStore.token
    authStore.setToken(authStore.adminToken)
    const res = await listUsers()
    users.value = res || []
    authStore.setToken(originalToken)
  } catch (e) {
    console.error('获取用户列表失败', e)
    toast.error('获取用户列表失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

async function handleSwitch(user) {
  try {
    // 用admin_token调sudo接口
    const originalToken = authStore.token
    authStore.setToken(authStore.adminToken)
    const res = await sudo(user.id)
    authStore.setToken(originalToken)
    
    // 切换到新用户的token和用户信息
    authStore.setAuth(res.access_token, res.user)
    toast.success(`已切换至 ${roleLabel[user.role] || user.role}: ${user.display_name}`)
    
    // 刷新页面，让系统重新加载
    const role = user.role.toLowerCase()
    if (role === 'manufacturer') {
      window.location.href = '/manufacturer'
    } else if (role === 'supplier') {
      window.location.href = '/supplier'
    } else if (role === 'auditor') {
      window.location.href = '/auditor'
    }
  } catch (e) {
    console.error('切换失败', e)
    toast.error('切换失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function handleRestoreAdmin() {
  // 恢复ADMIN token
  authStore.setToken(authStore.adminToken)
  try {
    // 重新获取ADMIN用户信息
    const me = await getMe()
    authStore.user = me
    localStorage.setItem('clarity_user', JSON.stringify(me))
    toast.success('已恢复ADMIN身份')
    window.location.href = '/admin'
  } catch (e) {
    console.error('恢复ADMIN失败', e)
    toast.error('恢复ADMIN失败，请重新登录')
    authStore.logout()
    window.location.href = '/login'
  }
}

onMounted(fetchUsers)
</script>

<template>
  <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-sm shadow-xl w-full max-w-lg overflow-hidden flex flex-col border border-slate-300 max-h-[90vh]">
      <!-- 头部 -->
      <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center shrink-0">
        <div>
          <h2 class="text-sm font-bold text-slate-800">切换角色账号</h2>
          <p class="text-xs text-slate-500 mt-1">ADMIN 模式：选择要模拟登录的账号</p>
        </div>
        <button @click="emit('close')" class="text-slate-400 hover:text-slate-700">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>

      <!-- 搜索 -->
      <div class="px-6 py-3 border-b border-slate-200 shrink-0">
        <div class="relative">
          <svg class="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
          </svg>
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索账号、企业名称或角色..."
            class="w-full border border-slate-300 rounded-sm pl-9 pr-3 py-2 text-sm focus:outline-none focus:border-slate-800 placeholder-slate-400"
          />
        </div>
      </div>

      <!-- 用户列表 -->
      <div class="flex-1 overflow-y-auto p-4 min-h-[200px]">
        <div v-if="loading" class="text-center py-8 text-sm text-slate-500">加载中...</div>
        <div v-else-if="filteredUsers.length === 0" class="text-center py-8 text-sm text-slate-500">暂无用户数据</div>
        <div v-else class="space-y-2">
          <div
            v-for="user in filteredUsers"
            :key="user.id"
            class="flex items-center justify-between p-3 border border-slate-200 rounded-sm hover:bg-slate-50 transition-colors"
          >
            <div class="flex items-center gap-3">
              <div class="w-8 h-8 rounded bg-slate-100 flex items-center justify-center text-slate-600 text-xs font-bold">
                {{ user.display_name?.charAt(0) || '?' }}
              </div>
              <div>
                <div class="text-sm font-bold text-slate-800">{{ user.display_name }}</div>
                <div class="text-xs text-slate-500 font-mono">{{ user.account }}</div>
              </div>
            </div>
            <div class="flex items-center gap-2">
              <span
                class="text-[10px] font-bold px-2 py-0.5 rounded-sm border"
                :class="roleBadgeClass[user.role] || 'text-slate-600 bg-slate-100 border-slate-200'"
              >
                {{ roleLabel[user.role] || user.role }}
              </span>
              <button
                @click="handleSwitch(user)"
                class="px-3 py-1.5 text-[11px] font-bold text-white bg-[#0f172a] hover:bg-slate-800 rounded-sm transition-colors"
              >
                切换
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部 -->
      <div class="px-6 py-3 border-t border-slate-200 bg-slate-50 flex justify-between items-center shrink-0">
        <span class="text-xs text-slate-500">共 {{ filteredUsers.length }} 个账号</span>
        <button
          v-if="!authStore.isAdmin && authStore.adminToken"
          @click="handleRestoreAdmin"
          class="px-4 py-2 text-xs font-bold text-slate-700 bg-white border border-slate-300 rounded-sm hover:bg-slate-50 transition-colors"
        >
          恢复 ADMIN
        </button>
      </div>
    </div>
  </div>
</template>
