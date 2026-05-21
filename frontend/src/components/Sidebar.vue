<script setup>
import { computed } from 'vue'
import { useToastStore } from '@/stores/toast'

const props = defineProps({
  user: { type: Object, default: null },
  currentSection: { type: String, default: 'project' },
  role: { type: String, default: 'MANUFACTURER' }
})

const emit = defineEmits(['switch-section', 'recharge'])
const toast = useToastStore()

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

function copyUid() {
  if (!props.user?.wallet_address) return
  navigator.clipboard.writeText(props.user.wallet_address).then(() => {
    toast.success('钱包地址已复制到剪贴板')
  }).catch(() => {
    toast.error('复制失败')
  })
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
  <aside class="w-64 bg-white border-r border-slate-200 flex flex-col shrink-0">
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
      <div class="w-full text-[10px] text-slate-400 mt-1 mb-5 text-center flex items-center justify-center gap-1">
        <span>链上地址: {{ user?.wallet_address ? user.wallet_address.slice(0, 6) + '...' + user.wallet_address.slice(-4) : '0x3F8A...9A2C' }}</span>
        <div class="relative group">
          <button
            v-if="user?.wallet_address"
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
        @click.prevent="emit('switch-section', item.key)"
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
