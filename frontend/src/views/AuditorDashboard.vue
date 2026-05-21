<script setup>
import { ref, onMounted, computed, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { getMe } from '@/api/auth'
import { listTasks, startAudit, submitReport, advanceToAcceptance } from '@/api/tasks'
import { listChainEvents } from '@/api/chain'
import { useToastStore } from '@/stores/toast'
import AppHeader from '@/components/AppHeader.vue'
import Sidebar from '@/components/Sidebar.vue'
import RechargeModal from '@/components/RechargeModal.vue'
import DispatchModal from '@/components/DispatchModal.vue'
import HelpGuideModal from '@/components/HelpGuideModal.vue'
import AdminSwitchModal from '@/components/AdminSwitchModal.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const toast = useToastStore()

const currentSection = ref(route.query.section || 'project')
const user = computed(() => authStore.user)
const preparedTasks = ref([])
const auditingTasks = ref([])
const chainEvents = ref([])
const loading = ref(false)

const showRechargeModal = ref(false)
const showDispatchModal = ref(false)
const dispatchTarget = ref(null)
const showHelpModal = ref(false)
const showAdminSwitchModal = ref(false)
const showReportModal = ref(false)
const reportTarget = ref(null)
const reportForm = reactive({
  miss_rate: 0.002,
  false_kill_rate: 0.034,
  concentration_ratio: 0.45,
  avg_fp: 0.05,
  arrogance: 0.12,
  map: 0.87,
  f1: 0.84,
  report_hash: ''
})

const preparedCount = computed(() => preparedTasks.value.length)
const auditingCount = computed(() => auditingTasks.value.length)

// 统计卡片数据（mock，实际可从接口获取）
const dailyFee = ref(240)
const weeklyFee = ref(1850)
const totalLocked = ref(45200)

async function fetchUser() {
  try {
    const res = await getMe()
    authStore.user = res
  } catch (e) {
    console.error('获取用户信息失败', e)
  }
}

async function fetchPreparedTasks() {
  try {
    const res = await listTasks({ status: 'PREPARED' })
    preparedTasks.value = res.items || res || []
  } catch (e) {
    console.error('获取就绪工单失败', e)
  }
}

async function fetchAuditingTasks() {
  try {
    const res = await listTasks({ status: 'AUDITING' })
    auditingTasks.value = res.items || res || []
  } catch (e) {
    console.error('获取执行中工单失败', e)
  }
}

async function fetchChainEvents() {
  try {
    const res = await listChainEvents({ limit: 20 })
    chainEvents.value = res.items || res || []
  } catch (e) {
    console.error('获取链上动态失败', e)
  }
}

async function loadAll() {
  loading.value = true
  await Promise.all([
    fetchUser(),
    fetchPreparedTasks(),
    fetchAuditingTasks(),
    fetchChainEvents()
  ])
  loading.value = false
}

function switchSection(section) {
  if (section === 'blockchain') {
    router.push('/blockchain')
    return
  }
  currentSection.value = section
  // 清除 URL query 参数，避免刷新时回到之前的 section
  if (route.query.section) {
    router.replace({ query: {} })
  }
}

function statusDisplay(status) {
  const map = {
    'PENDING': '等待供应商接入',
    'UPLOADING': '等待双方上传文件',
    'PREPARED': '等待审计节点计算',
    'AUDITING': '审计节点计算中',
    'PASS': '审计通过，待释放资金',
    'REJECT': '能力不足，申诉期中',
    'SLASH': '恶意作弊，申诉期中',
    'DISPUTED_AUDIT': '线上申诉中',
    'ACCEPTANCE': '线上审计通过，等待现场验收',
    'RECTIFICATION': '整改中',
    'DISPUTED_FIELD': '现场争议中',
    'ARBITRATING': '协会仲裁中',
    'COMPLETED': '项目已完成',
    'CANCELED': '项目已取消'
  }
  return map[status] || status
}

function formatHash(hash) {
  if (!hash || typeof hash !== 'string') return hash
  if (hash.startsWith('0x') && hash.length > 12) {
    return hash.slice(0, 6) + '...' + hash.slice(-4)
  }
  return hash
}

function openDispatch(task) {
  dispatchTarget.value = task
  showDispatchModal.value = true
}

async function handleDispatch(taskId) {
  try {
    await startAudit(taskId)
    toast.success('执行容器已创建，开始拉取数据与模型，状态将变为 AUDITING')
    showDispatchModal.value = false
    await Promise.all([fetchPreparedTasks(), fetchAuditingTasks()])
  } catch (e) {
    console.error('调度失败', e)
    toast.error('调度失败: ' + (e.response?.data?.detail || e.message))
  }
}

function goToMonitor(taskId) {
  router.push(`/monitor/${taskId}`)
}

function openReportModal(task) {
  reportTarget.value = task
  showReportModal.value = true
}

async function handleSubmitReport() {
  try {
    const payload = {
      miss_rate: reportForm.miss_rate,
      false_kill_rate: reportForm.false_kill_rate,
      concentration_ratio: reportForm.concentration_ratio,
      avg_fp: reportForm.avg_fp,
      arrogance: reportForm.arrogance,
      map: reportForm.map,
      f1: reportForm.f1,
      report_hash: reportForm.report_hash || `audit_report_${Date.now()}`
    }
    const res = await submitReport(reportTarget.value.id, payload)

    // 根据后端返回的实际判定结果决定后续操作
    const decision = res?.decision
    if (decision === 'PASS') {
      await advanceToAcceptance(reportTarget.value.id)
      toast.success('审计报告已提交，判定 PASS，30% 资金已释放，项目进入现场验收阶段')
    } else if (decision === 'REJECT') {
      toast.success('审计报告已提交，判定 REJECT（能力不足），进入 72h 申诉期')
    } else if (decision === 'SLASH') {
      toast.success('审计报告已提交，判定 SLASH（恶意作弊），进入 72h 申诉期')
    } else {
      toast.success('审计报告已提交')
    }

    showReportModal.value = false
    await Promise.all([fetchPreparedTasks(), fetchAuditingTasks()])
  } catch (e) {
    console.error('提交报告失败', e)
    toast.error('提交失败: ' + (e.response?.data?.detail || e.message))
  }
}

function handleRecharged() {
  showRechargeModal.value = false
  fetchUser()
}

function copyUid() {
  if (!user.value?.wallet_address) return
  navigator.clipboard.writeText(user.value.wallet_address).then(() => {
    toast.success('钱包地址已复制到剪贴板')
  }).catch(() => {
    toast.error('复制失败')
  })
}

function logout() {
  authStore.logout()
  router.push('/login')
}

onMounted(loadAll)
</script>

<template>
  <div class="h-screen flex flex-col overflow-hidden selection:bg-slate-200 selection:text-slate-900" style="font-family: 'Inter', -apple-system, sans-serif; background-color: #f1f5f9; color: #0f172a;">
    <AppHeader
      :current-section="currentSection"
      @switch-section="switchSection"
      @logout="logout"
      @show-help="showHelpModal = true"
      @show-admin-switch="showAdminSwitchModal = true"
    />

    <div class="flex-1 flex overflow-hidden">
      <!-- 审计节点专用侧边栏（不复用 Sidebar 组件，直接内联实现差异） -->
      <aside class="w-64 bg-white border-r border-slate-200 flex flex-col shrink-0">
        <!-- 个人信息区 -->
        <div class="p-6 flex flex-col items-center border-b border-slate-100">
          <div class="w-16 h-16 rounded bg-[#0f172a] flex items-center justify-center text-white mb-4 shadow-sm">
            <!-- 带对号的盾牌 -->
            <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
          </div>
          <div class="w-full text-base font-bold text-slate-800 leading-tight text-center">
            {{ user?.display_name || user?.username || '审计节点' }}
          </div>
          <div class="w-full text-[10px] text-slate-400 mt-1 mb-5 text-center flex items-center justify-center gap-1">
            <span>链上地址: {{ user?.wallet_address ? user.wallet_address.slice(0, 6) + '...' + user.wallet_address.slice(-4) : '0x9D4...F2A1' }}</span>
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

          <!-- 节点网络权限卡片 -->
          <div class="w-full bg-slate-50 border border-slate-200 rounded-sm p-3">
            <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">节点网络权限</div>
            <div class="flex items-end justify-between">
              <span class="text-sm font-bold text-slate-800 leading-none">共识审查节点</span>
              <span class="text-[10px] font-bold text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded-sm border border-emerald-200">已授权</span>
            </div>
          </div>
        </div>

        <!-- 左侧菜单 -->
        <nav class="p-4 space-y-1 flex-1">
          <a
            href="#"
            class="block px-4 py-2.5 text-sm rounded-sm transition-colors"
            :class="currentSection === 'project'
              ? 'font-bold text-slate-800 bg-slate-100'
              : 'font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900'"
            @click.prevent="switchSection('project')"
          >
            任务队列
          </a>
          <a
            href="#"
            class="block px-4 py-2.5 text-sm rounded-sm transition-colors"
            :class="currentSection === 'history'
              ? 'font-bold text-slate-800 bg-slate-100'
              : 'font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900'"
            @click.prevent="switchSection('history')"
          >
            历史凭证
          </a>
          <a
            href="#"
            class="block px-4 py-2.5 text-sm rounded-sm transition-colors"
            :class="currentSection === 'arbitration'
              ? 'font-bold text-slate-800 bg-slate-100'
              : 'font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900'"
            @click.prevent="switchSection('arbitration')"
          >
            申诉记录
          </a>
        </nav>

        <!-- 底部资金池卡片和区块链状态 -->
        <div class="p-4 border-t border-slate-200">
          <!-- 资金池卡片 -->
          <div class="bg-slate-50 p-4 rounded-sm border border-slate-200 mb-3">
            <div class="text-xs text-slate-500 mb-1">节点服务费池</div>
            <div class="text-lg font-bold text-slate-800">
              {{ (user?.balance || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
              <span class="text-[10px] text-slate-500 font-normal">points</span>
            </div>
            <div class="text-xs text-slate-500 mt-2 border-t border-slate-200 pt-2">
              待结算: {{ (user?.locked_balance || 0).toLocaleString() }} points
            </div>

            <button
              @click="showRechargeModal = true"
              class="w-full mt-3 py-2 bg-[#0f172a] hover:bg-slate-800 text-white text-xs font-bold rounded-sm transition-colors shadow-sm tracking-widest uppercase"
            >
              资金结算提取
            </button>
          </div>

          <!-- 区块链状态 -->
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

      <main class="flex-1 overflow-y-auto bg-slate-100 p-8">
        <!-- 任务队列 -->
        <div v-if="currentSection === 'project'">
          <div class="flex items-center justify-between mb-6">
            <div>
              <h2 class="text-lg font-bold text-slate-800">
                欢迎回来，{{ user?.display_name || user?.username || '机器视觉产业联盟' }}
              </h2>
              <p class="text-sm text-slate-600 mt-1">
                当前有 <span class="font-bold text-blue-700">{{ preparedCount }}</span> 个就绪工单等待调度，
                <span class="font-bold text-blue-600">{{ auditingCount }}</span> 个工单正在执行计算
              </p>
            </div>
          </div>

          <!-- 就绪工单 (双边均已就位) -->
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm mb-6 overflow-hidden">
            <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
              <h3 class="text-sm font-bold text-slate-800">就绪工单 (双边均已就位)</h3>
              <select class="text-xs border border-slate-300 rounded-sm px-2 py-1 text-slate-700 outline-none bg-white">
                <option>按资金池规模排序</option>
                <option>按时间排序</option>
              </select>
            </div>
            <div class="overflow-x-auto">
              <table class="w-full text-left border-collapse">
                <thead>
                  <tr class="bg-slate-100 text-slate-600 text-xs border-b border-slate-200">
                    <th class="px-6 py-3 font-medium">项目名称 / ID哈希</th>
                    <th class="px-6 py-3 font-medium">数据集与模型 Hash</th>
                    <th class="px-6 py-3 font-medium">质押资金规模</th>
                    <th class="px-6 py-3 font-medium text-right">操作</th>
                  </tr>
                </thead>
                <tbody class="text-sm divide-y divide-slate-200 bg-white">
                  <tr
                    v-for="task in preparedTasks"
                    :key="task.id"
                    class="hover:bg-slate-50 transition-colors"
                  >
                    <td class="px-6 py-4">
                      <div class="font-bold text-slate-800">{{ task.task_name || task.name }}</div>
                      <div class="text-xs text-slate-500 font-mono mt-1">ID: {{ formatHash(task.task_hash || task.id) }}</div>
                    </td>
                    <td class="px-6 py-4">
                      <div class="text-slate-600 text-[11px] font-mono">Data: {{ task.dataset_hash || 'QmXp...2H8s' }}</div>
                      <div class="text-slate-600 text-[11px] font-mono mt-1">Model: {{ task.model_hash || 'QmYa...9P1c' }}</div>
                    </td>
                    <td class="px-6 py-4">
                      <div class="text-slate-800 text-xs font-mono font-bold">
                        {{ task.stake_amount ? task.stake_amount.toLocaleString() + ' points' : '1,650 points' }}
                      </div>
                    </td>
                    <td class="px-6 py-4 text-right">
                      <button
                        @click="openDispatch(task)"
                        class="px-4 py-2 bg-[#0f172a] hover:bg-slate-800 text-white font-bold text-xs rounded-sm transition-colors"
                      >
                        调度计算节点
                      </button>
                    </td>
                  </tr>
                  <tr v-if="preparedTasks.length === 0">
                    <td colspan="4" class="px-6 py-8 text-center text-sm text-slate-500">
                      暂无就绪工单
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- 执行中的工单 -->
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm overflow-hidden mb-6">
            <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
              <h3 class="text-sm font-bold text-slate-800">执行中的工单</h3>
              <select class="text-xs border border-slate-300 rounded-sm px-2 py-1 text-slate-700 outline-none bg-white">
                <option>运行中</option>
                <option>已完成</option>
              </select>
            </div>
            <div class="overflow-x-auto">
              <table class="w-full text-left border-collapse">
                <thead>
                  <tr class="bg-slate-100 text-slate-600 text-xs border-b border-slate-200">
                    <th class="px-6 py-3 font-medium">项目名称 / ID哈希</th>
                    <th class="px-6 py-3 font-medium">执行节点</th>
                    <th class="px-6 py-3 font-medium">当前状态</th>
                    <th class="px-6 py-3 font-medium text-right">操作</th>
                  </tr>
                </thead>
                <tbody class="text-sm divide-y divide-slate-200 bg-white">
                  <tr
                    v-for="task in auditingTasks"
                    :key="task.id"
                    class="hover:bg-slate-50 transition-colors"
                  >
                    <td class="px-6 py-4">
                      <div class="font-bold text-slate-800">{{ task.task_name || task.name }}</div>
                      <div class="text-xs text-slate-500 font-mono mt-1">ID: {{ formatHash(task.task_hash || task.id) }}</div>
                    </td>
                    <td class="px-6 py-4">
                      <div class="text-slate-700 text-xs font-mono">{{ task.gpu_node || 'NODE-GPU-01 (RTX4060)' }}</div>
                    </td>
                    <td class="px-6 py-4">
                      <div class="flex items-center text-xs font-bold text-blue-700">
                        <span class="w-1.5 h-1.5 rounded-full bg-blue-600 mr-2 animate-pulse"></span>
                        审计节点计算中
                      </div>
                    </td>
                    <td class="px-6 py-4 text-right">
                      <div class="flex gap-2 justify-end">
                        <button
                          @click="goToMonitor(task.id)"
                          class="text-slate-600 hover:text-slate-900 font-bold text-xs bg-slate-100 px-3 py-1.5 rounded-sm border border-slate-300"
                        >
                          查看监控大屏
                        </button>
                        <button
                          @click="openReportModal(task)"
                          class="text-white font-bold text-xs bg-emerald-600 hover:bg-emerald-700 px-3 py-1.5 rounded-sm"
                        >
                          提交审计报告
                        </button>
                      </div>
                    </td>
                  </tr>
                  <tr v-if="auditingTasks.length === 0">
                    <td colspan="4" class="px-6 py-8 text-center text-sm text-slate-500">
                      暂无执行中的工单
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- 节点服务费统计 -->
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm overflow-hidden">
            <div class="px-6 py-4 border-b border-slate-200 bg-slate-50">
              <h3 class="text-sm font-bold text-slate-800">节点服务费统计</h3>
            </div>
            <div class="p-8 bg-white">
              <div class="grid grid-cols-3 gap-6">
                <div class="bg-slate-50 border border-slate-200 rounded-sm p-4">
                  <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">本日服务费</div>
                  <div class="text-xl font-bold text-slate-800 font-mono">
                    {{ dailyFee.toLocaleString() }} <span class="text-xs font-normal text-slate-500">points</span>
                  </div>
                </div>
                <div class="bg-slate-50 border border-slate-200 rounded-sm p-4">
                  <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">本周累计</div>
                  <div class="text-xl font-bold text-slate-800 font-mono">
                    {{ weeklyFee.toLocaleString() }} <span class="text-xs font-normal text-slate-500">points</span>
                  </div>
                </div>
                <div class="bg-slate-50 border border-slate-200 rounded-sm p-4">
                  <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">平台总锁定资金</div>
                  <div class="text-xl font-bold text-slate-800 font-mono">
                    {{ totalLocked.toLocaleString() }} <span class="text-xs font-normal text-slate-500">points</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

        </div>

        <!-- 历史凭证 -->
        <div v-if="currentSection === 'history'">
          <div class="flex items-center justify-between mb-6">
            <div>
              <h2 class="text-lg font-bold text-slate-800">历史凭证</h2>
              <p class="text-sm text-slate-600 mt-1">查看所有已完成审计的链上存证报告</p>
            </div>
          </div>
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm overflow-hidden">
            <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
              <h3 class="text-sm font-bold text-slate-800">历史项目审计记录</h3>
              <div class="flex gap-2">
                <input
                  type="text"
                  placeholder="输入项目ID或区块Hash查询"
                  class="text-xs border border-slate-300 rounded-sm px-3 py-1 w-56 outline-none focus:border-slate-800"
                />
                <button class="px-3 py-1 bg-slate-800 text-white text-xs font-bold rounded-sm">验证 Hash</button>
              </div>
            </div>
            <div class="overflow-x-auto">
              <table class="w-full text-left border-collapse">
                <thead>
                  <tr class="bg-slate-100 text-slate-600 text-xs border-b border-slate-200">
                    <th class="px-6 py-3 font-medium">项目名称 / ID哈希</th>
                    <th class="px-6 py-3 font-medium">线上定标结果</th>
                    <th class="px-6 py-3 font-medium">模型审计指标</th>
                    <th class="px-6 py-3 font-medium">存证时间</th>
                    <th class="px-6 py-3 font-medium text-right">操作</th>
                  </tr>
                </thead>
                <tbody class="text-sm divide-y divide-slate-200 bg-white">
                  <tr
                    v-for="task in preparedTasks.concat(auditingTasks).filter(t => t.status === 'COMPLETED' || t.status === 'REJECTED' || t.status === 'SLASH')"
                    :key="task.id"
                    class="hover:bg-slate-50 transition-colors"
                  >
                    <td class="px-6 py-4">
                      <div class="font-bold text-slate-800">{{ task.name }}</div>
                      <div class="font-mono text-xs text-slate-500 mt-1">{{ task.id }}</div>
                    </td>
                    <td class="px-6 py-4">
                      <span
                        class="text-xs font-bold px-2 py-1 rounded-sm border"
                        :class="task.status === 'COMPLETED'
                          ? 'text-slate-800 bg-slate-100 border-slate-300'
                          : task.status === 'SLASH'
                            ? 'text-rose-700 bg-rose-50 border-rose-200'
                            : 'text-slate-600 bg-slate-50 border-slate-300'"
                      >
                        {{ task.status === 'COMPLETED' ? 'PASS 通过' : task.status === 'SLASH' ? 'SLASH 罚没' : 'REJECT 拒收' }}
                      </span>
                    </td>
                    <td class="px-6 py-4">
                      <div class="text-xs font-bold" :class="task.status === 'COMPLETED' ? 'text-slate-700' : 'text-rose-600'">
                        漏杀: {{ task.final_fnr || '-' }}% | 误杀: {{ task.final_fpr || '-' }}%
                      </div>
                      <div class="text-[10px] text-slate-500 mt-1">
                        mAP: {{ task.final_map || '-' }}% | F1: {{ task.final_f1 || '-' }} | CR: {{ task.final_cr || '-' }}%
                      </div>
                    </td>
                    <td class="px-6 py-4 text-xs text-slate-600">
                      {{ task.completed_at || task.updated_at || '-' }}
                    </td>
                    <td class="px-6 py-4 text-right align-middle">
                      <button class="text-slate-700 bg-slate-100 border border-slate-300 hover:bg-slate-200 font-bold text-xs px-3 py-1.5 rounded-sm transition-colors">
                        查看链上存证
                      </button>
                    </td>
                  </tr>
                  <tr v-if="!preparedTasks.concat(auditingTasks).some(t => t.status === 'COMPLETED' || t.status === 'REJECTED' || t.status === 'SLASH')">
                    <td colspan="5" class="px-6 py-8 text-center text-sm text-slate-500">
                      暂无历史记录
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <!-- 申诉记录 -->
        <div v-if="currentSection === 'arbitration'">
          <div class="flex items-center justify-between mb-6">
            <div>
              <h2 class="text-lg font-bold text-slate-800">申诉记录</h2>
              <p class="text-sm text-slate-600 mt-1">查看所有争议申诉及仲裁处理状态</p>
            </div>
          </div>
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm overflow-hidden">
            <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
              <h3 class="text-sm font-bold text-slate-800">仲裁申诉记录</h3>
              <div class="flex gap-2">
                <input
                  type="text"
                  placeholder="输入项目ID或区块Hash查询"
                  class="text-xs border border-slate-300 rounded-sm px-3 py-1 w-56 outline-none focus:border-slate-800"
                />
                <button class="px-3 py-1 bg-slate-800 text-white text-xs font-bold rounded-sm">验证 Hash</button>
              </div>
            </div>
            <div class="overflow-x-auto">
              <table class="w-full text-left border-collapse">
                <thead>
                  <tr class="bg-slate-100 text-slate-600 text-xs border-b border-slate-200">
                    <th class="px-6 py-3 font-medium">项目名称 / ID哈希</th>
                    <th class="px-6 py-3 font-medium">争议类型</th>
                    <th class="px-6 py-3 font-medium">当前状态</th>
                    <th class="px-6 py-3 font-medium">申请时间</th>
                    <th class="px-6 py-3 font-medium text-right">操作</th>
                  </tr>
                </thead>
                <tbody class="text-sm divide-y divide-slate-200 bg-white">
                  <tr
                    v-for="task in preparedTasks.concat(auditingTasks).filter(t => t.status === 'DISPUTED_AUDIT' || t.status === 'DISPUTED_FIELD' || t.status === 'ARBITRATING')"
                    :key="task.id"
                    class="hover:bg-slate-50 transition-colors"
                  >
                    <td class="px-6 py-4">
                      <div class="font-bold text-slate-800">{{ task.name }}</div>
                      <div class="font-mono text-xs text-slate-500 mt-1">{{ task.id }}</div>
                    </td>
                    <td class="px-6 py-4">
                      <div class="text-xs text-slate-700">{{ task.dispute_type || '现场履约争议' }}</div>
                      <div class="text-xs text-slate-500 mt-1">{{ task.dispute_reason || '制造商质疑现场部署效果' }}</div>
                    </td>
                    <td class="px-6 py-4">
                      <span class="text-xs font-bold text-slate-700 bg-slate-100 px-2 py-1 rounded-sm border border-slate-300">协会仲裁中</span>
                    </td>
                    <td class="px-6 py-4 text-xs text-slate-600">
                      {{ task.dispute_at || task.updated_at || '-' }}
                    </td>
                    <td class="px-6 py-4 text-right">
                      <button class="text-slate-600 hover:text-slate-900 font-bold text-xs bg-slate-100 px-3 py-1.5 rounded-sm border border-slate-300">
                        查看进度
                      </button>
                    </td>
                  </tr>
                  <tr v-if="!preparedTasks.concat(auditingTasks).some(t => t.status === 'DISPUTED_AUDIT' || t.status === 'DISPUTED_FIELD' || t.status === 'ARBITRATING')">
                    <td colspan="5" class="px-6 py-8 text-center text-sm text-slate-500">
                      暂无申诉记录
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </main>
    </div>

    <RechargeModal
      v-if="showRechargeModal"
      :current-balance="user?.balance || 0"
      @close="showRechargeModal = false"
      @recharged="handleRecharged"
    />
    <DispatchModal
      v-if="showDispatchModal"
      :task="dispatchTarget"
      @close="showDispatchModal = false"
      @dispatch="handleDispatch"
    />
    <HelpGuideModal v-if="showHelpModal" @close="showHelpModal = false" />
    <AdminSwitchModal v-if="showAdminSwitchModal" @close="showAdminSwitchModal = false" />

    <!-- 提交审计报告弹窗 -->
    <div
      v-if="showReportModal"
      class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4"
    >
      <div class="bg-white rounded-sm shadow-xl w-full max-w-xl overflow-hidden flex flex-col border border-slate-300">
        <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
          <h2 class="text-sm font-bold text-slate-800">提交审计报告</h2>
          <button @click="showReportModal = false" class="text-slate-400 hover:text-slate-700">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
          </button>
        </div>

        <div class="p-6 space-y-4 bg-white">
          <div class="bg-blue-50 border border-blue-200 rounded-sm p-3">
            <div class="text-xs font-bold text-blue-800 mb-1">审计项目</div>
            <div class="text-[10px] text-blue-600">{{ reportTarget?.task_name }} (ID: {{ reportTarget?.id }})</div>
          </div>

          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-xs font-bold text-slate-700 mb-1">漏杀率</label>
              <input v-model.number="reportForm.miss_rate" type="number" step="0.001" class="w-full border border-slate-300 rounded-sm px-3 py-1.5 text-xs" />
            </div>
            <div>
              <label class="block text-xs font-bold text-slate-700 mb-1">误杀率</label>
              <input v-model.number="reportForm.false_kill_rate" type="number" step="0.001" class="w-full border border-slate-300 rounded-sm px-3 py-1.5 text-xs" />
            </div>
            <div>
              <label class="block text-xs font-bold text-slate-700 mb-1">注意力密度比</label>
              <input v-model.number="reportForm.concentration_ratio" type="number" step="0.01" class="w-full border border-slate-300 rounded-sm px-3 py-1.5 text-xs" />
            </div>
            <div>
              <label class="block text-xs font-bold text-slate-700 mb-1">平均误检数</label>
              <input v-model.number="reportForm.avg_fp" type="number" step="0.01" class="w-full border border-slate-300 rounded-sm px-3 py-1.5 text-xs" />
            </div>
            <div>
              <label class="block text-xs font-bold text-slate-700 mb-1">自信度偏差</label>
              <input v-model.number="reportForm.arrogance" type="number" step="0.01" class="w-full border border-slate-300 rounded-sm px-3 py-1.5 text-xs" />
            </div>
            <div>
              <label class="block text-xs font-bold text-slate-700 mb-1">mAP</label>
              <input v-model.number="reportForm.map" type="number" step="0.01" class="w-full border border-slate-300 rounded-sm px-3 py-1.5 text-xs" />
            </div>
            <div>
              <label class="block text-xs font-bold text-slate-700 mb-1">F1 Score</label>
              <input v-model.number="reportForm.f1" type="number" step="0.01" class="w-full border border-slate-300 rounded-sm px-3 py-1.5 text-xs" />
            </div>
            <div>
              <label class="block text-xs font-bold text-slate-700 mb-1">报告 Hash</label>
              <input v-model="reportForm.report_hash" type="text" placeholder="可选" class="w-full border border-slate-300 rounded-sm px-3 py-1.5 text-xs font-mono" />
            </div>
          </div>

          <div class="bg-slate-50 border border-slate-200 rounded-sm p-3">
            <div class="text-[10px] text-slate-500">判定预览：</div>
            <div class="text-xs font-bold mt-1"
              :class="{
                'text-emerald-600': reportForm.miss_rate <= 0.05 && reportForm.false_kill_rate <= 0.05 && reportForm.concentration_ratio >= 0.2,
                'text-rose-600': reportForm.concentration_ratio < 0.2 || (reportForm.avg_fp >= 0.1 && reportForm.arrogance >= 0.5),
                'text-amber-600': reportForm.miss_rate > 0.05 || reportForm.false_kill_rate > 0.05
              }"
            >
              {{ reportForm.miss_rate > 0.05 || reportForm.false_kill_rate > 0.05 ? 'REJECT（能力不足）' :
                 reportForm.concentration_ratio < 0.2 ? 'SLASH（涉嫌作弊）' :
                 reportForm.avg_fp >= 0.1 && reportForm.arrogance >= 0.5 ? 'SLASH（确信性犯错）' :
                 reportForm.avg_fp >= 0.1 ? 'REJECT（泛化不足）' : 'PASS（通过）' }}
            </div>
          </div>
        </div>

        <div class="px-6 py-4 border-t border-slate-200 bg-slate-50 flex justify-end gap-3">
          <button
            @click="showReportModal = false"
            class="px-4 py-2 text-xs font-bold text-slate-600 hover:text-slate-900 bg-white border border-slate-300 rounded-sm"
          >
            取消
          </button>
          <button
            @click="handleSubmitReport"
            class="px-4 py-2 text-xs font-bold text-white bg-[#0f172a] hover:bg-slate-800 rounded-sm"
          >
            提交审计报告
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #e2e8f0; }
::-webkit-scrollbar-thumb { background: #94a3b8; border-radius: 0px; }
</style>
