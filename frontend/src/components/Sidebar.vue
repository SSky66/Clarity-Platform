<script setup>
import { computed, ref } from 'vue'
import { useToastStore } from '@/stores/toast'
import { useMobileStore } from '@/stores/mobile'
import { assignWallet } from '@/api/auth'

const props = defineProps({
  user: { type: Object, default: null },
  currentSection: { type: String, default: 'project' },
  role: { type: String, default: 'MANUFACTURER' }
})

const emit = defineEmits(['switch-section', 'recharge', 'wallet-assigned'])
const toast = useToastStore()
const mobileStore = useMobileStore()

const isSupplier = computed(() => props.role === 'SUPPLIER')
const isAuditor = computed(() => props.role === 'AUDITOR')

const reputationScore = computed(() => props.user?.reputation_score ?? 70)

const reputationBadge = computed(() => {
  const score = reputationScore.value
  if (score >= 81) return { text: '优秀', class: 'text-emerald-700 bg-emerald-100 border-emerald-200' }
  if (score >= 61) return { text: '良好', class: 'text-blue-700 bg-blue-50 border-blue-200' }
  if (score >= 41) return { text: '普通', class: 'text-amber-700 bg-amber-100 border-amber-200' }
  return { text: '高危', class: 'text-rose-700 bg-rose-100 border-rose-200' }
})

const balance = computed(() => {
  const b = props.user?.balance || 0
  return b.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
})

const lockedBalance = computed(() => props.user?.locked_balance || 0)

const hasWallet = computed(() => !!props.user?.wallet_address)
const walletDisplay = computed(() => {
  if (hasWallet.value) {
    const addr = props.user.wallet_address
    return addr.slice(0, 6) + '...' + addr.slice(-4)
  }
  return '未分配'
})

const assigning = ref(false)

function handleMenuClick(key) {
  emit('switch-section', key)
  // 移动端点击菜单后自动关闭侧边栏
  if (mobileStore.isMobile || mobileStore.isTablet) {
    mobileStore.closeSidebar()
  }
}

async function copyUid() {
  if (!props.user?.wallet_address) return
  
  const text = props.user.wallet_address
  
  // 优先使用现代 API
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      toast.success('钱包地址已复制到剪贴板')
      return
    } catch (e) {
      console.log('clipboard API failed, fallback')
    }
  }
  
  // 降级方案：用 textarea + execCommand
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.left = '-9999px'
  document.body.appendChild(textarea)
  textarea.select()
  
  try {
    const success = document.execCommand('copy')
    document.body.removeChild(textarea)
    if (success) {
      toast.success('钱包地址已复制到剪贴板')
    } else {
      toast.error('复制失败，请手动复制')
    }
  } catch (e) {
    document.body.removeChild(textarea)
    toast.error('复制失败，请手动复制')
  }
}

async function handleAssignWallet() {
  if (assigning.value) return
  assigning.value = true
  try {
    const res = await assignWallet()
    toast.success('链上钱包分配成功！')
    emit('wallet-assigned', res)
  } catch (e) {
    console.error('分配钱包失败', e)
    const detail = e.response?.data?.detail
    const msg = typeof detail === 'string' ? detail : JSON.stringify(detail)
    toast.error('分配失败: ' + (msg || e.message))
  } finally {
    assigning.value = false
  }
}

const menuItems = computed(() => {
  if (isAuditor.value) {
    return [
      { key: 'project', label: '任务队列' },
      { key: 'history', label: '历史凭证' },
      { key: 'arbitration', label: '申诉记录' }
    ]
  }
  return [
    { key: 'project', label: '项目管理' },
    { key: 'history', label: '历史凭证' },
    { key: 'arbitration', label: '申诉记录' }
  ]
})
</script>

<template>
  <!-- 移动端遮罩层 -->
  <div
    v-if="mobileStore.sidebarOpen && (mobileStore.isMobile || mobileStore.isTablet)"
    class="fixed inset-0 bg-slate-900/50 z-40 md:hidden"
    @click="mobileStore.closeSidebar"
  ></div>
  <aside
    class="bg-white border-r border-slate-200 flex flex-col shrink-0 transition-transform duration-300 ease-in-out z-50"
    :class="{
      'fixed inset-y-0 left-0 w-64 transform': mobileStore.isMobile || mobileStore.isTablet,
      '-translate-x-full': (mobileStore.isMobile || mobileStore.isTablet) && !mobileStore.sidebarOpen,
      'translate-x-0': (mobileStore.isMobile || mobileStore.isTablet) && mobileStore.sidebarOpen,
      'w-64 relative': !mobileStore.isMobile && !mobileStore.isTablet
    }"
  >
    <!-- 个人信息区 -->
    <div class="p-6 flex flex-col items-center border-b border-slate-100">
      <div class="w-16 h-16 rounded bg-[#0f172a] flex items-center justify-center text-white mb-4 shadow-sm">
        <!-- 审计节点：带对号的盾牌 -->
        <svg v-if="isAuditor" class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
        </svg>
        <!-- 制造商：芯片图标 -->
        <svg v-else-if="!isSupplier" class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"></path>
        </svg>
        <!-- 供应商：代码/算法图标 -->
        <svg v-else class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"/>
        </svg>
      </div>
      <div class="w-full text-base font-bold text-slate-800 leading-tight text-center">
        {{ user?.display_name || user?.username || (isSupplier ? '供应商' : isAuditor.value ? '审计节点' : '制造商') }}
      </div>
      <div class="w-full text-[10px] mt-1 mb-5 text-center flex items-center justify-center gap-1">
        <span
          :class="hasWallet ? 'text-slate-400' : 'text-rose-500 font-bold'"
        >
          链上地址: {{ walletDisplay }}
        </span>
        <!-- 已分配：复制按钮 -->
        <div v-if="hasWallet" class="relative group">
          <button
            @click="copyUid"
            class="text-slate-400 hover:text-slate-600 transition-colors p-0.5"
          >
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path>
            </svg>
          </button>
          <div class="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-1 bg-slate-800 text-white text-[10px] rounded-sm whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
            复制钱包地址
          </div>
        </div>
        <!-- 未分配：刷新按钮 -->
        <button
          v-else
          @click="handleAssignWallet"
          :disabled="assigning"
          class="text-rose-500 hover:text-rose-700 transition-colors p-0.5 disabled:opacity-50"
          title="分配链上钱包"
        >
          <svg v-if="!assigning" class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
          </svg>
          <svg v-else class="w-3 h-3 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
          </svg>
        </button>
      </div>

      <!-- 审计节点：节点网络权限卡片 -->
      <div v-if="isAuditor" class="w-full bg-slate-50 border border-slate-200 rounded-sm p-3">
        <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">节点网络权限</div>
        <div class="flex items-end justify-between">
          <span class="text-sm font-bold text-slate-800 leading-none">共识审查节点</span>
          <span class="text-[10px] font-bold text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded-sm border border-emerald-200">已授权</span>
        </div>
      </div>
      <!-- 制造商/供应商：信誉评级卡片 -->
      <div v-else class="w-full bg-slate-50 border border-slate-200 rounded-sm p-3">
        <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">
          {{ isSupplier ? '履约信誉评级' : '合规信誉评级' }}
        </div>
        <div class="flex items-end justify-between">
          <span class="text-xl font-bold text-slate-800 leading-none">{{ reputationScore }}</span>
          <span
            class="text-[10px] font-bold px-2 py-0.5 rounded-sm border"
            :class="reputationBadge.class"
          >
            {{ reputationBadge.text }}
          </span>
        </div>
      </div>
    </div>

    <!-- 左侧菜单 -->
    <nav class="p-4 space-y-1 flex-1">
      <a
        v-for="item in menuItems"
        :key="item.key"
        href="#"
        class="block px-4 py-2.5 text-sm rounded-sm transition-colors"
        :class="currentSection === item.key
          ? 'font-bold text-slate-800 bg-slate-100'
          : 'font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900'"
        @click.prevent="handleMenuClick(item.key)"
      >
        {{ item.label }}
      </a>
    </nav>

    <!-- 资金池模块 & 区块链状态 -->
    <div class="p-4 border-t border-slate-200">
      <div class="bg-slate-50 p-4 rounded-sm border border-slate-200 mb-3">
        <div class="text-xs text-slate-500 mb-1">{{ isAuditor ? '节点服务费池' : '智能合约资金池' }}</div>
        <div class="text-lg font-bold text-slate-800">
          {{ balance }} <span class="text-[10px] text-slate-500 font-normal">points</span>
        </div>
        <div class="text-xs text-slate-500 mt-2 border-t border-slate-200 pt-2">
          {{ isAuditor ? '待结算' : '履约锁定' }}: {{ lockedBalance.toLocaleString() }} points
        </div>

        <button
          @click="emit('recharge')"
          class="w-full mt-3 py-2 bg-[#0f172a] hover:bg-slate-800 text-white text-xs font-bold rounded-sm transition-colors shadow-sm tracking-widest uppercase"
        >
          {{ isAuditor ? '资金结算提取' : '链上资金充值' }}
        </button>
      </div>

      <div class="bg-slate-50 p-4 rounded-sm border border-slate-200">
        <div class="flex items-center gap-2 mb-3">
          <div class="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_4px_#10b981] animate-pulse"></div>
          <div class="text-[10px] font-bold uppercase tracking-widest text-slate-500">FISCO BCOS 状态</div>
        </div>
        <div class="text-[10px] text-slate-500 text-center py-1">
          请在「链上查询」页面查看实时数据
        </div>
      </div>
    </div>
  </aside>
</template>
