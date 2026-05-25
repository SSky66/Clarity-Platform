<script setup>
import { ref, computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { changePassword, changeAccount } from '@/api/auth'

const emit = defineEmits(['close'])

const auth = useAuthStore()
const toast = useToastStore()
const user = computed(() => auth.user)

const activeTab = ref('password')
const canChangeAccount = computed(() => user.value?.role === 'ADMIN')

const passwordForm = ref({
  oldPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const accountForm = ref({
  newAccount: ''
})

const loading = ref(false)
const showOldPwd = ref(false)
const showNewPwd = ref(false)
const showConfirmPwd = ref(false)

function switchTab(tab) {
  activeTab.value = tab
  passwordForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
  accountForm.value = { newAccount: '' }
  showOldPwd.value = false
  showNewPwd.value = false
  showConfirmPwd.value = false
}

function sanitize(str) {
  return str.replace(/[^a-zA-Z0-9_\-@.]/g, '')
}

async function handleChangePassword() {
  const { oldPassword, newPassword, confirmPassword } = passwordForm.value

  if (!oldPassword || !newPassword || !confirmPassword) {
    toast.error('请填写所有字段')
    return
  }
  if (newPassword.length < 8) {
    toast.error('新密码至少8位')
    return
  }
  if (newPassword !== confirmPassword) {
    toast.error('两次输入的新密码不一致')
    return
  }

  loading.value = true
  try {
    await changePassword(oldPassword, newPassword)
    toast.success('密码修改成功！请使用新密码重新登录')
    emit('close')
    setTimeout(() => {
      auth.logout()
      window.location.href = '/login'
    }, 1500)
  } catch (e) {
    console.error('修改密码失败', e)
    const detail = e.response?.data?.detail
    toast.error('修改失败: ' + (detail || e.message))
  } finally {
    loading.value = false
  }
}

async function handleChangeAccount() {
  const { newAccount } = accountForm.value

  if (!newAccount || newAccount.length < 5) {
    toast.error('新账号最少5位')
    return
  }

  loading.value = true
  try {
    await changeAccount(newAccount)
    toast.success('账号修改成功！请使用新账号重新登录')
    emit('close')
    setTimeout(() => {
      auth.logout()
      window.location.href = '/login'
    }, 1500)
  } catch (e) {
    console.error('修改账号失败', e)
    const detail = e.response?.data?.detail
    toast.error('修改失败: ' + (detail || e.message))
  } finally {
    loading.value = false
  }
}

const roleLabel = computed(() => {
  const map = {
    MANUFACTURER: '制造商',
    SUPPLIER: '供应商',
    AUDITOR: '审计节点',
    ADMIN: '系统管理员'
  }
  return map[user.value?.role] || '用户'
})
</script>

<template>
  <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4"
    @click.self="emit('close')">
    <div class="bg-white rounded-sm shadow-xl w-full max-w-md overflow-hidden flex flex-col border border-slate-200">
      <!-- 头部 -->
      <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
        <div class="flex items-center gap-3">
          <div class="w-9 h-9 rounded-sm bg-[#0f172a] flex items-center justify-center text-white">
            <!-- 审计节点：带对号的盾牌 -->
            <svg v-if="user?.role === 'AUDITOR'" class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
            <!-- 制造商：芯片图标 -->
            <svg v-else-if="user?.role === 'MANUFACTURER'" class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"></path>
            </svg>
            <!-- 供应商：代码/算法图标 -->
            <svg v-else-if="user?.role === 'SUPPLIER'" class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"/>
            </svg>
            <!-- ADMIN：默认用户图标 -->
            <svg v-else class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
            </svg>
          </div>
          <div>
            <h2 class="text-sm font-bold text-slate-800">个人管理</h2>
            <p class="text-[10px] text-slate-500">{{ user?.display_name }} · {{ roleLabel }}</p>
          </div>
        </div>
        <button @click="emit('close')" class="text-slate-400 hover:text-slate-700 p-1">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>

      <!-- Tab 切换 -->
      <div class="flex">
        <button @click="switchTab('password')"
          class="flex-1 py-3 text-xs font-bold transition-colors"
          :class="activeTab === 'password' ? 'text-[#0f172a] bg-slate-100' : 'text-slate-500 hover:bg-slate-50'">
          修改密码
        </button>
        <button v-if="canChangeAccount" @click="switchTab('account')"
          class="flex-1 py-3 text-xs font-bold transition-colors"
          :class="activeTab === 'account' ? 'text-[#0f172a] bg-slate-100' : 'text-slate-500 hover:bg-slate-50'">
          修改账号
        </button>
      </div>

      <!-- 修改密码 -->
      <div v-if="activeTab === 'password'" class="p-6 space-y-5">
        <div class="input-wrapper border border-slate-300 rounded-sm bg-white flex items-stretch overflow-hidden h-11">
          <div class="bg-slate-50 w-24 flex items-center justify-center border-r border-slate-300 shrink-0">
            <span class="text-slate-600 font-bold text-xs tracking-widest">当前密码</span>
          </div>
          <input v-model="passwordForm.oldPassword" :type="showOldPwd ? 'text' : 'password'"
            placeholder="••••••••"
            autocomplete="new-password"
            class="flex-1 bg-transparent px-4 text-xs text-slate-800 focus:outline-none tracking-widest placeholder-slate-400 font-bold" />
          <button type="button" @click="showOldPwd = !showOldPwd" class="px-3 text-slate-400 hover:text-slate-600 focus:outline-none">
            <svg v-if="!showOldPwd" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
            </svg>
            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"/>
            </svg>
          </button>
        </div>

        <div class="input-wrapper border border-slate-300 rounded-sm bg-white flex items-stretch overflow-hidden h-11">
          <div class="bg-slate-50 w-24 flex items-center justify-center border-r border-slate-300 shrink-0">
            <span class="text-slate-600 font-bold text-xs tracking-widest">新密码</span>
          </div>
          <input v-model="passwordForm.newPassword" :type="showNewPwd ? 'text' : 'password'"
            placeholder="••••••••"
            autocomplete="new-password"
            class="flex-1 bg-transparent px-4 text-xs text-slate-800 focus:outline-none tracking-widest placeholder-slate-400 font-bold" />
          <button type="button" @click="showNewPwd = !showNewPwd" class="px-3 text-slate-400 hover:text-slate-600 focus:outline-none">
            <svg v-if="!showNewPwd" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
            </svg>
            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"/>
            </svg>
          </button>
        </div>

        <div class="input-wrapper border border-slate-300 rounded-sm bg-white flex items-stretch overflow-hidden h-11"
          :class="passwordForm.confirmPassword && passwordForm.newPassword !== passwordForm.confirmPassword ? 'border-rose-300' : ''">
          <div class="bg-slate-50 w-24 flex items-center justify-center border-r border-slate-300 shrink-0">
            <span class="text-slate-600 font-bold text-xs tracking-widest">确认密码</span>
          </div>
          <input v-model="passwordForm.confirmPassword" :type="showConfirmPwd ? 'text' : 'password'"
            placeholder="••••••••"
            autocomplete="new-password"
            class="flex-1 bg-transparent px-4 text-xs text-slate-800 focus:outline-none tracking-widest placeholder-slate-400 font-bold" />
          <button type="button" @click="showConfirmPwd = !showConfirmPwd" class="px-3 text-slate-400 hover:text-slate-600 focus:outline-none">
            <svg v-if="!showConfirmPwd" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
            </svg>
            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"/>
            </svg>
          </button>
        </div>
        <p v-if="passwordForm.confirmPassword && passwordForm.newPassword !== passwordForm.confirmPassword"
          class="text-[11px] text-rose-500 -mt-3">两次输入的密码不一致</p>

        <div class="pt-1">
          <button @click="handleChangePassword" :disabled="loading"
            class="w-full bg-[#0f172a] hover:bg-slate-800 disabled:opacity-50 text-white font-bold text-xs h-11 rounded-sm transition-colors shadow-sm tracking-widest flex items-center justify-center gap-2">
            <span>{{ loading ? '处理中...' : '确认修改' }}</span>
          </button>
        </div>
      </div>

      <!-- 修改账号 -->
      <div v-if="activeTab === 'account'" class="p-6 space-y-5">
        <div class="bg-slate-50 border border-slate-200 rounded-sm p-3">
          <div class="text-xs text-slate-500">当前账号</div>
          <div class="text-sm font-bold text-slate-800 font-mono mt-0.5">{{ user?.account }}</div>
        </div>

        <div class="input-wrapper border border-slate-300 rounded-sm bg-white flex items-stretch overflow-hidden h-11">
          <div class="bg-slate-50 w-24 flex items-center justify-center border-r border-slate-300 shrink-0">
            <span class="text-slate-600 font-bold text-xs tracking-widest">新账号</span>
          </div>
          <input v-model="accountForm.newAccount" type="text" placeholder="设置新登录账号（至少5位）"
            @input="accountForm.newAccount = sanitize($event.target.value)"
            class="flex-1 bg-transparent px-4 text-xs text-slate-800 focus:outline-none placeholder-slate-400 font-bold" />
        </div>

        <div class="pt-1">
          <button @click="handleChangeAccount" :disabled="loading"
            class="w-full bg-[#0f172a] hover:bg-slate-800 disabled:opacity-50 text-white font-bold text-xs h-11 rounded-sm transition-colors shadow-sm tracking-widest flex items-center justify-center gap-2">
            <span>{{ loading ? '处理中...' : '确认修改' }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.input-wrapper {
  transition: all 0.2s ease;
}
.input-wrapper:focus-within {
  border-color: #0f172a;
  box-shadow: 0 0 0 1px #0f172a;
}

/* 隐藏浏览器自带的密码显示按钮 */
input[type="password"]::-ms-reveal,
input[type="password"]::-ms-clear {
  display: none;
}

input[type="password"]::-webkit-contacts-auto-fill-button,
input[type="password"]::-webkit-credentials-auto-fill-button {
  visibility: hidden;
  display: none !important;
  pointer-events: none;
  position: absolute;
  right: 0;
}
</style>
