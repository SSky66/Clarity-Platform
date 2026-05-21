<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { listUsers } from '@/api/auth'
import { listTasks, createAppeal } from '@/api/tasks'
import { listChainEventsV2, getChainStats } from '@/api/chain'
import { listPendingAppeals, resolveAppeal, assignArbitrator } from '@/api/appeals'
import AppHeader from '@/components/AppHeader.vue'
import AdminSwitchModal from '@/components/AdminSwitchModal.vue'

const router = useRouter()
const toast = useToastStore()
const authStore = useAuthStore()

const users = ref([])
const tasks = ref([])
const chainEvents = ref([])
const chainStats = ref({
  connected: false,
  block_height: null,
  total_transactions: 0,
  active_nodes: 0,
  total_onchain_records: 0
})
const loading = ref(false)
const showAdminSwitchModal = ref(false)

// 仲裁面板状态
const activeTab = ref('overview') // overview | arbitration
const pendingAppeals = ref([])
const appealsLoading = ref(false)
const showAssignModal = ref(false)
const assignTarget = ref(null)
const showResolveModal = ref(false)
const resolveTarget = ref(null)
// 与 Dispute.sol / AppealResolve 对齐: result 1/2/3 + resolution
const resolveForm = ref({
  result: 1,
  resolution: ''
})

const user = computed(() => authStore.user)

// 统计数据
const totalUsers = computed(() => users.value.length)
const manufacturerCount = computed(() => users.value.filter(u => u.role === 'MANUFACTURER').length)
const supplierCount = computed(() => users.value.filter(u => u.role === 'SUPPLIER').length)
const auditorCount = computed(() => users.value.filter(u => u.role === 'AUDITOR').length)

const totalTasks = computed(() => tasks.value.length)
const pendingTasks = computed(() => tasks.value.filter(t => t.status === 'PENDING').length)
const uploadingTasks = computed(() => tasks.value.filter(t => t.status === 'UPLOADING').length)
const preparedTasks = computed(() => tasks.value.filter(t => t.status === 'PREPARED').length)
const auditingTasks = computed(() => tasks.value.filter(t => t.status === 'AUDITING').length)
const completedTasks = computed(() => tasks.value.filter(t => t.status === 'COMPLETED').length)
const arbitratingTasks = computed(() => tasks.value.filter(t => t.status === 'ARBITRATING').length)

// 整改超时后未创建 Appeal 记录的项目（DISPUTED_FIELD 状态）
const fieldDisputeTasks = computed(() => tasks.value.filter(t => t.status === 'DISPUTED_FIELD'))

async function fetchData() {
  loading.value = true
  try {
    const [usersRes, tasksRes, eventsRes, statsRes] = await Promise.all([
      listUsers(),
      listTasks({}),
      listChainEventsV2({ limit: 10 }),
      getChainStats()
    ])
    users.value = usersRes || []
    tasks.value = tasksRes || []
    chainEvents.value = eventsRes || []
    chainStats.value = statsRes || chainStats.value
  } catch (e) {
    console.error('获取数据失败', e)
    toast.error('获取数据失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

async function fetchPendingAppeals() {
  appealsLoading.value = true
  try {
    const res = await listPendingAppeals()
    pendingAppeals.value = res || []
  } catch (e) {
    console.error('获取待仲裁列表失败', e)
    toast.error('获取待仲裁列表失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    appealsLoading.value = false
  }
}

// 为 DISPUTED_FIELD 状态的项目自动创建 Appeal 记录
async function handleCreateFieldAppeal(task) {
  try {
    await createAppeal({
      task_id: task.id,
      appeal_type: 'FIELD_DOWNGRADE',
      reason: '整改期结束后自动升级的现场争议（由管理员创建申诉记录）'
    })
    toast.success('已为此项目创建现场申诉记录')
    await fetchPendingAppeals()
    await fetchData()
  } catch (e) {
    console.error('创建申诉记录失败', e)
    toast.error('创建失败: ' + (e.response?.data?.detail || e.message))
  }
}

// 根据申诉类型获取可用的裁决选项
function getResultOptions(appeal) {
  if (!appeal) return []
  const type = appeal.appeal_type
  if (type === 'AUDIT_REJECT' || type === 'AUDIT_SLASH') {
    // 线上申诉: 1=维持原判, 2=REJECT→PASS反转, 3=SLASH反转(制造商投毒)
    return [
      { value: 1, label: '维持原判', desc: '保持原审计结果不变' },
      { value: 2, label: 'REJECT→PASS 反转', desc: '能力不足改判为通过，进入现场验收' },
      { value: 3, label: 'SLASH 反转（制造商投毒）', desc: '供应商清白，制造商作弊' }
    ]
  } else {
    // 现场申诉: 1=履约降级, 2=恶意违约（等同SLASH）
    return [
      { value: 1, label: '履约降级', desc: '供应商部分违约，扣锁定金额的30%补偿制造商' },
      { value: 2, label: '恶意违约（等同SLASH）', desc: '供应商现场作弊，扣锁定金额的10%补偿制造商，90%入系统池' }
    ]
  }
}

function openAssignModal(appeal) {
  assignTarget.value = appeal
  showAssignModal.value = true
}

async function handleAssignArbitrator() {
  // admin 自己充当仲裁员，自动指派自己
  try {
    await assignArbitrator(assignTarget.value.id, {
      arbitrator_id: user.value.id
    })
    toast.success('已指派仲裁员（管理员）')
    showAssignModal.value = false
    await fetchPendingAppeals()
  } catch (e) {
    console.error('指派仲裁员失败', e)
    toast.error('指派失败: ' + (e.response?.data?.detail || e.message))
  }
}

function openResolveModal(appeal) {
  resolveTarget.value = appeal
  resolveForm.value = {
    result: 1,
    resolution: ''
  }
  showResolveModal.value = true
}

async function handleResolve() {
  if (!resolveForm.value.resolution.trim()) {
    toast.error('请输入仲裁决议说明')
    return
  }
  try {
    await resolveAppeal(resolveTarget.value.id, {
      result: resolveForm.value.result,
      resolution: resolveForm.value.resolution
    })
    toast.success('仲裁裁决已提交')
    showResolveModal.value = false
    await fetchPendingAppeals()
    await fetchData()
  } catch (e) {
    console.error('仲裁失败', e)
    toast.error('仲裁失败: ' + (e.response?.data?.detail || e.message))
  }
}

function switchTab(tab) {
  activeTab.value = tab
  if (tab === 'arbitration') {
    fetchPendingAppeals()
  }
}

function switchSection(section) {
  if (section === 'blockchain') {
    router.push('/blockchain')
  }
}

function logout() {
  authStore.logout()
  router.push('/login')
}

function formatHash(hash) {
  if (!hash || typeof hash !== 'string') return hash
  if (hash.startsWith('0x') && hash.length > 12) {
    return hash.slice(0, 6) + '...' + hash.slice(-4)
  }
  return hash
}

function formatDate(dt) {
  if (!dt) return '-'
  const d = new Date(dt)
  return d.toLocaleString('zh-CN')
}

onMounted(fetchData)
</script>

<template>
  <div class="h-screen flex flex-col overflow-hidden selection:bg-slate-200 selection:text-slate-900" style="font-family: 'Inter', -apple-system, sans-serif; background-color: #f1f5f9; color: #0f172a;">
    <AppHeader
      current-section="admin"
      @switch-section="switchSection"
      @logout="logout"
      @show-admin-switch="showAdminSwitchModal = true"
    />

    <div class="flex-1 overflow-y-auto p-8">
      <!-- 页面标题与标签切换 -->
      <div class="mb-6 flex items-center justify-between">
        <div>
          <h2 class="text-lg font-bold text-slate-800">系统管理控制台</h2>
          <p class="text-sm text-slate-600 mt-1">
            欢迎回来，{{ user?.display_name || '系统管理员' }} — 系统全局监控与账号管理
          </p>
        </div>
        <div class="flex bg-white border border-slate-200 rounded-sm overflow-hidden">
          <button
            @click="switchTab('overview')"
            class="px-4 py-2 text-xs font-bold transition-colors"
            :class="activeTab === 'overview' ? 'bg-[#0f172a] text-white' : 'text-slate-600 hover:bg-slate-50'"
          >
            概览
          </button>
          <button
            @click="switchTab('arbitration')"
            class="px-4 py-2 text-xs font-bold transition-colors relative"
            :class="activeTab === 'arbitration' ? 'bg-[#0f172a] text-white' : 'text-slate-600 hover:bg-slate-50'"
          >
            争议仲裁
            <span
              v-if="pendingAppeals.length > 0 && activeTab !== 'arbitration'"
              class="absolute -top-1 -right-1 w-4 h-4 bg-rose-500 text-white text-[9px] font-bold rounded-full flex items-center justify-center"
            >{{ pendingAppeals.length }}</span>
          </button>
        </div>
      </div>

      <!-- ========== 概览标签 ========== -->
      <div v-if="activeTab === 'overview'">
        <!-- 用户统计卡片 -->
        <div class="grid grid-cols-4 gap-6 mb-6">
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm p-6">
            <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">注册用户总数</div>
            <div class="text-xl font-bold text-slate-800 font-mono">{{ totalUsers }}</div>
            <div class="text-xs text-slate-400 mt-2">系统内所有非管理员的用户</div>
          </div>
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm p-6">
            <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">制造商</div>
            <div class="text-xl font-bold text-blue-700 font-mono">{{ manufacturerCount }}</div>
            <div class="text-xs text-slate-400 mt-2">发布验收需求的企业</div>
          </div>
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm p-6">
            <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">供应商</div>
            <div class="text-xl font-bold text-emerald-700 font-mono">{{ supplierCount }}</div>
            <div class="text-xs text-slate-400 mt-2">提供视觉模型的企业</div>
          </div>
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm p-6">
            <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">审计节点</div>
            <div class="text-xl font-bold text-purple-700 font-mono">{{ auditorCount }}</div>
            <div class="text-xs text-slate-400 mt-2">执行审计计算的节点</div>
          </div>
        </div>

        <!-- 项目统计 + 链上状态 -->
        <div class="grid grid-cols-3 gap-6 mb-6">
          <!-- 项目状态分布 -->
          <div class="col-span-2 bg-white border border-slate-200 rounded-sm shadow-sm overflow-hidden">
            <div class="px-6 py-4 border-b border-slate-200 bg-slate-50">
              <h3 class="text-sm font-bold text-slate-800">项目状态分布</h3>
            </div>
            <div class="p-6">
              <div class="grid grid-cols-3 gap-4">
                <div class="bg-slate-50 border border-slate-200 rounded-sm p-4 text-center">
                  <div class="text-xs text-slate-500 mb-1">项目总数</div>
                  <div class="text-xl font-bold text-slate-800 font-mono">{{ totalTasks }}</div>
                </div>
                <div class="bg-slate-50 border border-slate-200 rounded-sm p-4 text-center">
                  <div class="text-xs text-slate-500 mb-1">待接单</div>
                  <div class="text-xl font-bold text-slate-600 font-mono">{{ pendingTasks }}</div>
                </div>
                <div class="bg-slate-50 border border-slate-200 rounded-sm p-4 text-center">
                  <div class="text-xs text-slate-500 mb-1">上传中</div>
                  <div class="text-xl font-bold text-slate-600 font-mono">{{ uploadingTasks }}</div>
                </div>
                <div class="bg-slate-50 border border-slate-200 rounded-sm p-4 text-center">
                  <div class="text-xs text-slate-500 mb-1">就绪待审</div>
                  <div class="text-xl font-bold text-blue-700 font-mono">{{ preparedTasks }}</div>
                </div>
                <div class="bg-slate-50 border border-slate-200 rounded-sm p-4 text-center">
                  <div class="text-xs text-slate-500 mb-1">审计中</div>
                  <div class="text-xl font-bold text-purple-700 font-mono">{{ auditingTasks }}</div>
                </div>
                <div class="bg-slate-50 border border-slate-200 rounded-sm p-4 text-center">
                  <div class="text-xs text-slate-500 mb-1">已完成</div>
                  <div class="text-xl font-bold text-emerald-700 font-mono">{{ completedTasks }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 链上状态 -->
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm overflow-hidden">
            <div class="px-6 py-4 border-b border-slate-200 bg-slate-50">
              <h3 class="text-sm font-bold text-slate-800">链上状态</h3>
            </div>
            <div class="p-6 space-y-4">
              <div class="flex justify-between items-center">
                <span class="text-xs text-slate-500">当前区块高度</span>
                <span class="text-sm font-bold font-mono text-slate-800">
                  {{ chainStats.block_height ? '#' + chainStats.block_height.toLocaleString() : '--' }}
                </span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-xs text-slate-500">总交易笔数</span>
                <span class="text-sm font-bold font-mono text-slate-800">{{ chainStats.total_transactions }}</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-xs text-slate-500">共识节点数量</span>
                <span class="text-sm font-bold font-mono text-slate-800">{{ chainStats.active_nodes }}</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-xs text-slate-500">链上存证数量</span>
                <span class="text-sm font-bold font-mono text-slate-800">{{ chainStats.total_onchain_records }}</span>
              </div>
              <div class="pt-3 border-t border-slate-200">
                <div class="flex items-center gap-2">
                  <div class="w-2 h-2 rounded-full" :class="chainStats.connected ? 'bg-emerald-500' : 'bg-rose-500'"></div>
                  <span class="text-xs text-slate-600">{{ chainStats.connected ? '网络正常' : '未接入' }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 用户列表 -->
        <div class="bg-white border border-slate-200 rounded-sm shadow-sm overflow-hidden">
          <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
            <h3 class="text-sm font-bold text-slate-800">系统用户列表</h3>
            <span class="text-xs text-slate-500">共 {{ totalUsers }} 个用户</span>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse">
              <thead>
                <tr class="bg-slate-100 text-slate-600 text-xs border-b border-slate-200">
                  <th class="px-6 py-3 font-medium">ID</th>
                  <th class="px-6 py-3 font-medium">账号</th>
                  <th class="px-6 py-3 font-medium">企业名称</th>
                  <th class="px-6 py-3 font-medium">角色</th>
                  <th class="px-6 py-3 font-medium">余额</th>
                  <th class="px-6 py-3 font-medium">信誉分</th>
                  <th class="px-6 py-3 font-medium">注册时间</th>
                </tr>
              </thead>
              <tbody class="text-sm divide-y divide-slate-200 bg-white">
                <tr v-for="u in users" :key="u.id" class="hover:bg-slate-50 transition-colors">
                  <td class="px-6 py-4 font-mono text-xs text-slate-500">{{ u.id }}</td>
                  <td class="px-6 py-4 font-mono text-xs text-slate-700">{{ u.account }}</td>
                  <td class="px-6 py-4 font-bold text-slate-800">{{ u.display_name }}</td>
                  <td class="px-6 py-4">
                    <span
                      class="text-[10px] font-bold px-2 py-0.5 rounded-sm border"
                      :class="{
                        'text-blue-700 bg-blue-50 border-blue-200': u.role === 'MANUFACTURER',
                        'text-emerald-700 bg-emerald-50 border-emerald-200': u.role === 'SUPPLIER',
                        'text-purple-700 bg-purple-50 border-purple-200': u.role === 'AUDITOR'
                      }"
                    >
                      {{ u.role === 'MANUFACTURER' ? '制造商' : u.role === 'SUPPLIER' ? '供应商' : '审计节点' }}
                    </span>
                  </td>
                  <td class="px-6 py-4 font-mono text-xs text-slate-700">{{ u.balance?.toLocaleString() }} pts</td>
                  <td class="px-6 py-4 font-mono text-xs text-slate-700">
                    {{ u.role === 'AUDITOR' ? '-' : u.reputation_score }}
                  </td>
                  <td class="px-6 py-4 text-xs text-slate-500">{{ u.created_at }}</td>
                </tr>
                <tr v-if="users.length === 0">
                  <td colspan="7" class="px-6 py-8 text-center text-sm text-slate-500">暂无用户数据</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ========== 争议仲裁标签 ========== -->
      <div v-if="activeTab === 'arbitration'">
        <!-- 仲裁统计卡片 -->
        <div class="grid grid-cols-4 gap-6 mb-6">
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm p-6">
            <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">待仲裁申诉</div>
            <div class="text-xl font-bold text-rose-600 font-mono">{{ pendingAppeals.length }}</div>
            <div class="text-xs text-slate-400 mt-2">需要协会裁决的争议</div>
          </div>
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm p-6">
            <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">仲裁中项目</div>
            <div class="text-xl font-bold text-amber-600 font-mono">{{ arbitratingTasks }}</div>
            <div class="text-xs text-slate-400 mt-2">已裁决但未终态</div>
          </div>
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm p-6">
            <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">线上审计争议</div>
            <div class="text-xl font-bold text-slate-700 font-mono">{{ pendingAppeals.filter(a => a.appeal_type === 'AUDIT_REJECT' || a.appeal_type === 'AUDIT_SLASH').length }}</div>
            <div class="text-xs text-slate-400 mt-2">对审计结果不满</div>
          </div>
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm p-6">
            <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">现场履约争议</div>
            <div class="text-xl font-bold text-slate-700 font-mono">{{ pendingAppeals.filter(a => a.appeal_type === 'FIELD_DOWNGRADE' || a.appeal_type === 'FIELD_MALICE').length }}</div>
            <div class="text-xs text-slate-400 mt-2">对现场验收不满</div>
          </div>
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm p-6">
            <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">待创建申诉</div>
            <div class="text-xl font-bold text-rose-600 font-mono">{{ fieldDisputeTasks.length }}</div>
            <div class="text-xs text-slate-400 mt-2">整改超时未创建 Appeal</div>
          </div>
        </div>

        <!-- 待仲裁列表 -->
        <div class="bg-white border border-slate-200 rounded-sm shadow-sm overflow-hidden">
          <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
            <h3 class="text-sm font-bold text-slate-800">待仲裁申诉列表</h3>
            <span class="text-xs text-slate-500">共 {{ pendingAppeals.length }} 条待处理</span>
          </div>

          <div v-if="appealsLoading" class="p-8 text-center text-sm text-slate-500">加载中...</div>
          <div v-else-if="pendingAppeals.length === 0" class="p-8 text-center text-sm text-slate-500">
            暂无待仲裁申诉
          </div>
          <!-- 待创建申诉的项目（整改超时升级但无 Appeal 记录） -->
          <div v-if="fieldDisputeTasks.length > 0" class="mb-4 bg-rose-50 border border-rose-200 rounded-sm p-4">
            <div class="text-xs font-bold text-rose-700 mb-2">以下项目已升级至 DISPUTED_FIELD，但尚未创建申诉记录</div>
            <div class="space-y-2">
              <div v-for="task in fieldDisputeTasks" :key="task.id" class="flex items-center justify-between bg-white rounded-sm p-3 border border-rose-100">
                <div>
                  <span class="text-xs font-bold text-slate-800">{{ task.task_name }}</span>
                  <span class="text-[10px] text-slate-400 ml-2">ID: {{ task.id }}</span>
                </div>
                <button
                  @click="handleCreateFieldAppeal(task)"
                  class="px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold rounded-sm"
                >
                  创建申诉记录
                </button>
              </div>
            </div>
          </div>

          <div v-else class="divide-y divide-slate-200">
            <div
              v-for="appeal in pendingAppeals"
              :key="appeal.id"
              class="p-6 hover:bg-slate-50 transition-colors"
            >
              <div class="flex items-start justify-between">
                <div class="flex-1">
                  <!-- 头部信息 -->
                  <div class="flex items-center gap-3 mb-2">
                    <span class="text-sm font-bold text-slate-800">申诉 #{{ appeal.id }}</span>
                    <span
                      class="text-[10px] font-bold px-2 py-0.5 rounded-sm border"
                      :class="(appeal.appeal_type === 'AUDIT_REJECT' || appeal.appeal_type === 'AUDIT_SLASH') ? 'text-purple-700 bg-purple-50 border-purple-200' : 'text-amber-700 bg-amber-50 border-amber-200'"
                    >
                      {{ (appeal.appeal_type === 'AUDIT_REJECT' || appeal.appeal_type === 'AUDIT_SLASH') ? '线上审计争议' : '现场履约争议' }}
                    </span>
                    <span class="text-[10px] text-slate-400">{{ formatDate(appeal.created_at) }}</span>
                  </div>

                  <!-- 项目信息 -->
                  <div class="text-xs text-slate-600 mb-2">
                    <span class="font-bold">项目:</span> {{ appeal.task_name || '未知项目' }}
                    <span class="font-mono text-slate-400 ml-2">{{ formatHash(appeal.task_hash) }}</span>
                  </div>

                  <!-- 双方信息 -->
                  <div class="flex gap-6 text-xs text-slate-600 mb-3">
                    <div>
                      <span class="text-slate-400">制造商:</span>
                      <span class="font-bold text-blue-700 ml-1">{{ appeal.manufacturer_name || '-' }}</span>
                      <span class="font-mono text-slate-400 ml-1">{{ appeal.manufacturer_margin ? appeal.manufacturer_margin.toLocaleString() + ' pts' : '-' }}</span>
                    </div>
                    <div>
                      <span class="text-slate-400">供应商:</span>
                      <span class="font-bold text-emerald-700 ml-1">{{ appeal.supplier_name || '-' }}</span>
                      <span class="font-mono text-slate-400 ml-1">{{ appeal.supplier_margin ? appeal.supplier_margin.toLocaleString() + ' pts' : '-' }}</span>
                    </div>
                  </div>

                  <!-- 申诉理由 -->
                  <div class="bg-slate-50 border border-slate-200 rounded-sm p-3 mb-3">
                    <div class="text-[10px] text-slate-400 uppercase tracking-wider mb-1">申诉理由</div>
                    <div class="text-xs text-slate-700 leading-relaxed">{{ appeal.reason }}</div>
                  </div>

                  <!-- 证据 -->
                  <div v-if="appeal.evidence_hash" class="text-xs text-slate-500">
                    <span class="text-slate-400">证据Hash:</span>
                    <span class="font-mono">{{ appeal.evidence_hash }}</span>
                  </div>
                </div>

                <!-- 操作按钮 -->
                <div class="ml-6 shrink-0 flex flex-col gap-2">
                  <button
                    v-if="appeal.status === 'PENDING'"
                    @click="openAssignModal(appeal)"
                    class="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white text-xs font-bold rounded-sm transition-colors shadow-sm"
                  >
                    指派仲裁员
                  </button>
                  <button
                    v-if="appeal.status === 'ARBITRATING'"
                    @click="openResolveModal(appeal)"
                    class="px-4 py-2 bg-[#0f172a] hover:bg-slate-800 text-white text-xs font-bold rounded-sm transition-colors shadow-sm"
                  >
                    执行仲裁
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 指派仲裁员弹窗 -->
    <div
      v-if="showAssignModal"
      class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4"
    >
      <div class="bg-white rounded-sm shadow-xl w-full max-w-md overflow-hidden flex flex-col border border-slate-300">
        <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
          <div>
            <h2 class="text-sm font-bold text-slate-800">指派仲裁员</h2>
            <p class="text-xs text-slate-500 mt-1">申诉 #{{ assignTarget?.id }} — {{ assignTarget?.task_name }}</p>
          </div>
          <button @click="showAssignModal = false" class="text-slate-400 hover:text-slate-700">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
          </button>
        </div>
        <div class="p-6">
          <p class="text-sm text-slate-700 mb-4">
            当前策略：由系统管理员（您自己）兼任仲裁员角色。指派后，申诉将进入「仲裁中」状态，您可以执行裁决。
          </p>
          <div class="bg-slate-50 border border-slate-200 rounded-sm p-3">
            <div class="text-xs text-slate-500">仲裁员</div>
            <div class="text-sm font-bold text-slate-800">{{ user?.display_name || '系统管理员' }} (ID: {{ user?.id }})</div>
          </div>
        </div>
        <div class="px-6 py-4 border-t border-slate-200 bg-slate-50 flex justify-end gap-3">
          <button
            @click="showAssignModal = false"
            class="px-5 py-2 text-xs font-bold text-slate-600 hover:text-slate-900 bg-white border border-slate-300 rounded-sm"
          >
            取消
          </button>
          <button
            @click="handleAssignArbitrator"
            class="px-5 py-2 text-xs font-bold text-white bg-amber-600 hover:bg-amber-700 rounded-sm"
          >
            确认指派
          </button>
        </div>
      </div>
    </div>

    <!-- 仲裁裁决弹窗 -->
    <div
      v-if="showResolveModal"
      class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4"
    >
      <div class="bg-white rounded-sm shadow-xl w-full max-w-lg overflow-hidden flex flex-col border border-slate-300">
        <!-- 头部 -->
        <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
          <div>
            <h2 class="text-sm font-bold text-slate-800">仲裁裁决</h2>
            <p class="text-xs text-slate-500 mt-1">申诉 #{{ resolveTarget?.id }} — {{ resolveTarget?.task_name }}</p>
          </div>
          <button @click="showResolveModal = false" class="text-slate-400 hover:text-slate-700">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
          </button>
        </div>

        <!-- 表单 -->
        <div class="p-6 space-y-5">
          <!-- 裁决结果 -->
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-2">裁决结果</label>
            <div class="space-y-2">
              <label
                v-for="opt in getResultOptions(resolveTarget)"
                :key="opt.value"
                class="flex items-start gap-3 cursor-pointer p-3 rounded-sm border transition-colors"
                :class="resolveForm.result === opt.value
                  ? 'bg-slate-50 border-slate-800'
                  : 'bg-white border-slate-200 hover:border-slate-400'"
              >
                <input
                  v-model.number="resolveForm.result"
                  type="radio"
                  :value="opt.value"
                  class="mt-0.5"
                />
                <div>
                  <div class="text-xs font-bold text-slate-800">{{ opt.label }}</div>
                  <div class="text-[10px] text-slate-500 mt-0.5">{{ opt.desc }}</div>
                </div>
              </label>
            </div>
          </div>

          <!-- 裁决说明 -->
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-2">仲裁决议说明</label>
            <textarea
              v-model="resolveForm.resolution"
              rows="4"
              placeholder="输入仲裁裁决的详细说明..."
              class="w-full border border-slate-300 rounded-sm px-3 py-2 text-sm focus:outline-none focus:border-slate-800 placeholder-slate-400 resize-none"
            ></textarea>
          </div>
        </div>

        <!-- 底部 -->
        <div class="px-6 py-4 border-t border-slate-200 bg-slate-50 flex justify-end gap-3">
          <button
            @click="showResolveModal = false"
            class="px-5 py-2 text-xs font-bold text-slate-600 hover:text-slate-900 bg-white border border-slate-300 rounded-sm"
          >
            取消
          </button>
          <button
            @click="handleResolve"
            class="px-5 py-2 text-xs font-bold text-white bg-[#0f172a] hover:bg-slate-800 rounded-sm"
          >
            提交裁决
          </button>
        </div>
      </div>
    </div>

    <AdminSwitchModal v-if="showAdminSwitchModal" @close="showAdminSwitchModal = false" />
  </div>
</template>

<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #e2e8f0; }
::-webkit-scrollbar-thumb { background: #94a3b8; border-radius: 0px; }
</style>
