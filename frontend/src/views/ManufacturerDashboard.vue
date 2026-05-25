<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { getMe } from '@/api/auth'
import { listTasks, getTaskStats } from '@/api/tasks'
import { listChainEvents } from '@/api/chain'
import { useToastStore } from '@/stores/toast'
import AppHeader from '@/components/AppHeader.vue'
import Sidebar from '@/components/Sidebar.vue'
import CreateTaskModal from '@/components/CreateTaskModal.vue'
import UploadDatasetModal from '@/components/UploadDatasetModal.vue'
import FieldSignModal from '@/components/FieldSignModal.vue'
import RechargeModal from '@/components/RechargeModal.vue'
import HelpGuideModal from '@/components/HelpGuideModal.vue'
import AdminSwitchModal from '@/components/AdminSwitchModal.vue'
import ProfileModal from '@/components/ProfileModal.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const toast = useToastStore()

const currentSection = ref(route.query.section || 'project')
const user = computed(() => authStore.user)
const tasks = ref([])
const stats = ref({ pending: 0, running: 0, total: 0 })
const chainEvents = ref([])
const loading = ref(false)

const showCreateModal = ref(false)
const showUploadModal = ref(false)
const showFieldSignModal = ref(false)
const showRechargeModal = ref(false)
const showHelpModal = ref(false)
const showAdminSwitchModal = ref(false)
const showProfileModal = ref(false)

const uploadTarget = ref({ id: '', name: '' })
const fieldSignTarget = ref({ id: '', name: '' })

const pendingCount = computed(() => stats.value.pending || 0)
const runningCount = computed(() => stats.value.running || 0)

async function fetchUser() {
  try {
    const res = await getMe()
    authStore.updateUser(res)
  } catch (e) {
    console.error('获取用户信息失败', e)
  }
}

async function fetchTasks() {
  try {
    const res = await listTasks({ role: 'manufacturer' })
    tasks.value = res.items || res || []
  } catch (e) {
    console.error('获取项目列表失败', e)
  }
}

async function fetchStats() {
  try {
    const res = await getTaskStats()
    stats.value = res
  } catch (e) {
    console.error('获取统计数据失败', e)
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
  await Promise.all([fetchUser(), fetchTasks(), fetchStats(), fetchChainEvents()])
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

function openUpload(task) {
  uploadTarget.value = task
  showUploadModal.value = true
}

function openFieldSign(task) {
  fieldSignTarget.value = { id: task.id, name: task.name }
  showFieldSignModal.value = true
}

function handleTaskCreated() {
  showCreateModal.value = false
  fetchTasks()
  fetchStats()
}

function handleDatasetUploaded() {
  showUploadModal.value = false
  fetchTasks()
  fetchStats()
}

function handleFieldSigned() {
  showFieldSignModal.value = false
  fetchTasks()
  fetchStats()
}

function handleRecharged() {
  showRechargeModal.value = false
  fetchUser()
}

async function copyProjectId(task) {
  const hash = task.task_hash || task.id
  
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(hash)
      toast.success('项目哈希已复制到剪贴板！请通过线下安全渠道发送给您的专属算法供应商。')
      return
    } catch (e) {
      console.log('clipboard API failed, fallback')
    }
  }
  
  const textarea = document.createElement('textarea')
  textarea.value = hash
  textarea.style.position = 'fixed'
  textarea.style.left = '-9999px'
  document.body.appendChild(textarea)
  textarea.select()
  
  try {
    const success = document.execCommand('copy')
    document.body.removeChild(textarea)
    if (success) {
      toast.success('项目哈希已复制到剪贴板！请通过线下安全渠道发送给您的专属算法供应商。')
    } else {
      toast.error('复制失败，请手动复制')
    }
  } catch (e) {
    document.body.removeChild(textarea)
    toast.error('复制失败，请手动复制')
  }
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
      @show-profile="showProfileModal = true"
    />

    <div class="flex-1 flex overflow-hidden">
      <Sidebar
        :user="user"
        :current-section="currentSection"
        role="MANUFACTURER"
        @switch-section="switchSection"
        @recharge="showRechargeModal = true"
        @wallet-assigned="fetchUser"
      />

      <main class="flex-1 overflow-y-auto bg-slate-100 p-8">
        <!-- 项目大厅 -->
        <div v-if="currentSection === 'project'">
          <div class="flex items-center justify-between mb-6">
            <div>
              <h2 class="text-lg font-bold text-slate-800">
                欢迎回来，{{ user?.display_name || user?.username || '制造商' }}
              </h2>
              <p class="text-sm text-slate-600 mt-1">
                当前有 <span class="font-bold text-blue-600">{{ pendingCount }}</span> 个项目待验收，
                <span class="font-bold text-blue-600">{{ runningCount }}</span> 个项目执行中
              </p>
            </div>
            <button
              @click="showCreateModal = true"
              class="px-6 py-2.5 bg-[#0f172a] hover:bg-slate-800 text-white text-sm font-bold rounded-sm shadow-sm transition-colors"
            >
              创建新的验收需求
            </button>
          </div>

          <!-- 待办提醒区 -->
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm mb-6 border-l-4 border-l-blue-600 overflow-hidden">
            <div class="px-6 py-3 border-b border-slate-200 bg-blue-50/50 flex justify-between items-center">
              <h3 class="text-sm font-bold text-slate-800">待办提醒</h3>
            </div>
            <div class="flex flex-col">
              <div
                v-for="task in tasks.filter(t => t.status === 'UPLOADING' || t.status === 'ACCEPTANCE' || t.status === 'RECTIFICATION')"
                :key="task.id"
                class="p-6 flex items-center justify-between bg-white border-b border-slate-100 last:border-b-0"
              >
                <div>
                  <div class="text-sm font-bold text-slate-800 mb-1">
                    项目 [{{ task.task_name || task.name }}]
                    {{ task.status === 'UPLOADING' ? '等待上传数据' :
                       task.status === 'RECTIFICATION' ? '整改中' : '线上预验收已通过' }}
                  </div>
                  <div class="text-xs text-slate-500">
                    {{ task.status === 'UPLOADING' ? '供应商已接单，请上传测试集数据包。' :
                       task.status === 'RECTIFICATION' ? '供应商正在整改中，整改期结束后需再次验收。' :
                       '供应商已完成边缘端部署。请进行现场联调，并与供应商共同完成最终的双重签名验收。' }}
                  </div>
                </div>
                <button
                  v-if="task.status === 'UPLOADING'"
                  @click="openUpload(task)"
                  class="px-4 py-2 text-xs font-bold text-blue-700 bg-blue-50 border border-blue-200 rounded-sm hover:bg-blue-100 transition-colors"
                >
                  点击上传数据
                </button>
                <button
                  v-else-if="task.status === 'RECTIFICATION'"
                  class="px-4 py-2 text-xs font-bold text-amber-700 bg-amber-50 border border-amber-200 rounded-sm cursor-default"
                >
                  整改中
                </button>
                <button
                  v-else
                  @click="openFieldSign(task)"
                  class="px-4 py-2 text-xs font-bold text-white bg-blue-600 rounded-sm hover:bg-blue-700 transition-colors shadow-sm"
                >
                  现场验收签名
                </button>
              </div>
              <div v-if="!tasks.some(t => t.status === 'UPLOADING' || t.status === 'ACCEPTANCE' || t.status === 'RECTIFICATION')" class="p-6 text-sm text-slate-500 bg-white">
                暂无待办事项
              </div>
            </div>
          </div>

          <!-- 项目大厅列表 -->
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm overflow-hidden">
            <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
              <h3 class="text-sm font-bold text-slate-800">我发布的项目</h3>
              <select class="text-xs border border-slate-300 rounded-sm px-2 py-1 text-slate-700 outline-none bg-white">
                <option>全部状态</option>
                <option>待处理</option>
                <option>审计中</option>
              </select>
            </div>
            <div class="overflow-x-auto">
              <table class="w-full text-left border-collapse">
                <thead>
                  <tr class="bg-slate-100 text-slate-600 text-xs border-b border-slate-200">
                    <th class="px-6 py-3 font-medium">项目名称 / ID哈希</th>
                    <th class="px-6 py-3 font-medium">验收标准</th>
                    <th class="px-6 py-3 font-medium">担保方式</th>
                    <th class="px-6 py-3 font-medium">对方信誉</th>
                    <th class="px-6 py-3 font-medium">当前状态</th>
                    <th class="px-6 py-3 font-medium text-right">操作</th>
                  </tr>
                </thead>
                <tbody class="text-sm divide-y divide-slate-200 bg-white">
                  <tr v-for="task in tasks" :key="task.id" class="hover:bg-slate-50 transition-colors">
                    <td class="px-6 py-4">
                      <div class="font-bold text-slate-800">{{ task.task_name || task.name }}</div>
                      <div class="text-xs text-slate-500 font-mono mt-1">ID: {{ formatHash(task.task_hash || task.id) }}</div>
                    </td>
                    <td class="px-6 py-4">
                      <div class="text-slate-800 text-xs font-bold">
                        漏杀 &lt; {{ ((task.target_fnr || 0.005) * 100).toFixed(1) }}%, 误杀 &lt; {{ ((task.target_fpr || 0.05) * 100).toFixed(1) }}%
                      </div>
                      <div class="text-slate-500 text-[10px] mt-0.5">
                        mAP@0.5 &gt; {{ ((task.target_map || 0.85) * 100).toFixed(0) }}%, F1 &gt; {{ task.target_f1 || 0.8 }}
                      </div>
                    </td>
                    <td class="px-6 py-4">
                      <div class="text-slate-800 text-xs">
                        {{ task.guarantee_mode === 'insurance' ? '协会保险' : task.guarantee_mode === 'HIGH' ? '全额保证金' : '-' }}
                      </div>
                    </td>
                    <td class="px-6 py-4">
                      <!-- UPLOADING 阶段显示对方信誉积分 -->
                      <div v-if="task.status === 'UPLOADING' && task.supplier_reputation !== undefined && task.supplier_reputation !== null">
                        <div class="flex items-center gap-1.5">
                          <span class="text-xs font-bold text-slate-800">{{ task.supplier_reputation }}</span>
                          <span
                            class="text-[10px] font-bold px-1.5 py-0.5 rounded-sm border"
                            :class="{
                              'text-emerald-700 bg-emerald-100 border-emerald-200': task.supplier_reputation >= 81,
                              'text-blue-700 bg-blue-50 border-blue-200': task.supplier_reputation >= 61 && task.supplier_reputation <= 80,
                              'text-amber-700 bg-amber-100 border-amber-200': task.supplier_reputation >= 41 && task.supplier_reputation <= 60,
                              'text-rose-700 bg-rose-100 border-rose-200': task.supplier_reputation <= 40
                            }"
                          >
                            {{ task.supplier_reputation >= 81 ? '优秀' : task.supplier_reputation >= 61 ? '良好' : task.supplier_reputation >= 41 ? '普通' : '高危' }}
                          </span>
                        </div>
                        <div class="text-[10px] text-slate-400 mt-0.5">{{ task.supplier_name || '供应商' }}</div>
                      </div>
                      <span v-else class="text-xs text-slate-400">-</span>
                    </td>
                    <td class="px-6 py-4">
                      <div
                        class="flex items-center text-xs font-bold"
                        :class="{
                          'text-slate-600': task.status === 'PENDING' || task.status === 'UPLOADING',
                          'text-slate-800': task.status === 'ACCEPTANCE',
                          'text-blue-700': task.status === 'AUDITING'
                        }"
                      >
                        <span
                          class="w-1.5 h-1.5 rounded-full mr-2"
                          :class="{
                            'bg-slate-400': task.status === 'PENDING' || task.status === 'UPLOADING',
                            'bg-slate-700': task.status === 'ACCEPTANCE',
                            'bg-blue-600 animate-pulse': task.status === 'AUDITING'
                          }"
                        ></span>
                        {{ statusDisplay(task.status) }}
                      </div>
                    </td>
                    <td class="px-6 py-4 text-right">
                      <button
                        v-if="task.status === 'UPLOADING'"
                        @click="openUpload(task)"
                        class="text-slate-700 bg-slate-100 border border-slate-300 hover:bg-slate-200 font-bold text-xs px-3 py-1.5 rounded-sm transition-colors"
                      >
                        点击上传数据
                      </button>
                      <button
                        v-else-if="task.status === 'ACCEPTANCE'"
                        @click="openFieldSign(task)"
                        class="text-slate-700 bg-slate-100 border border-slate-300 hover:bg-slate-200 font-bold text-xs px-3 py-1.5 rounded-sm transition-colors"
                      >
                        现场验收签名
                      </button>
                      <button
                        v-else
                        @click="copyProjectId(task)"
                        class="text-slate-700 bg-slate-100 border border-slate-300 hover:bg-slate-200 font-bold text-xs px-3 py-1.5 rounded-sm transition-colors"
                      >
                        复制项目哈希
                      </button>
                    </td>
                  </tr>
                  <tr v-if="tasks.length === 0">
                    <td colspan="5" class="px-6 py-8 text-center text-sm text-slate-500">
                      暂无项目数据
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- 链上履约动态 -->
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm mt-6 overflow-hidden">
            <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
              <h3 class="text-sm font-bold text-slate-800">链上消息动态</h3>
              <span class="text-[10px] text-slate-500 uppercase tracking-wider font-bold">Real-time On-chain Logs</span>
            </div>
            <div class="p-6">
              <div class="relative border-l border-slate-200 ml-3 space-y-6 pb-2">
                <div
                  v-for="(event, idx) in chainEvents.slice(0, 10)"
                  :key="idx"
                  class="relative pl-6"
                >
                  <div class="absolute -left-[0.375rem] top-[0.375rem] w-3 h-3 rounded-full bg-slate-400 shadow-[0_0_0_4px_#ffffff]"></div>
                  <div class="flex items-center gap-2 mb-1">
                    <span class="text-xs font-bold text-slate-800">[{{ event.event_type || '链上事件' }}] {{ event.task_name || '' }}</span>
                    <span class="text-[10px] text-slate-400 font-mono">{{ event.time_display || event.created_at }}</span>
                  </div>
                  <div class="text-xs text-slate-600 leading-relaxed">
                    {{ event.description || event.detail || '暂无详情' }}
                  </div>
                </div>
                <div v-if="chainEvents.length === 0" class="relative pl-6 text-sm text-slate-500">
                  <div class="absolute -left-[0.375rem] top-[0.375rem] w-3 h-3 rounded-full bg-slate-300 shadow-[0_0_0_4px_#ffffff]"></div>
                  暂无链上动态
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
              <p class="text-sm text-slate-600 mt-1">查看所有具备防篡改效力的链上可解释性技术报告</p>
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
                  <tr v-for="task in tasks.filter(t => t.status === 'COMPLETED' || t.status === 'REJECTED' || t.status === 'SLASH')" :key="task.id" class="hover:bg-slate-50 transition-colors">
                    <td class="px-6 py-4">
                      <div class="font-bold text-slate-800">{{ task.name }}</div>
                      <div class="font-mono text-xs text-slate-500 mt-1">{{ task.id }}</div>
                    </td>
                    <td class="px-6 py-4">
                      <span
                        class="text-xs font-bold px-2 py-1 rounded-sm border"
                        :class="task.status === 'COMPLETED' ? 'text-slate-800 bg-slate-100 border-slate-300' : 'text-slate-600 bg-slate-50 border-slate-300'"
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
                  <tr v-if="!tasks.some(t => t.status === 'COMPLETED' || t.status === 'REJECTED')">
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
              <p class="text-sm text-slate-600 mt-1">查看所有争议申诉及预言机处理状态</p>
            </div>
          </div>
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm overflow-hidden">
            <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
              <h3 class="text-sm font-bold text-slate-800">历史争议申诉记录</h3>
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
                  <tr v-for="task in tasks.filter(t => t.status === 'DISPUTED_AUDIT' || t.status === 'DISPUTED_FIELD' || t.status === 'ARBITRATING')" :key="task.id" class="hover:bg-slate-50 transition-colors">
                    <td class="px-6 py-4">
                      <div class="font-bold text-slate-800">{{ task.name }}</div>
                      <div class="font-mono text-xs text-slate-500 mt-1">{{ task.id }}</div>
                    </td>
                    <td class="px-6 py-4">
                      <div class="text-xs text-slate-700">{{ task.dispute_type === 'AUDIT' ? '审计结果争议' : task.dispute_type === 'FIELD' ? '现场履约争议' : '验收标准争议' }}</div>
                      <div class="text-xs text-slate-500 mt-1">{{ task.dispute_reason || '预验收通过，但制造商拒绝签收物理部署' }}</div>
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
                  <tr v-if="!tasks.some(t => t.status === 'ARBITRATING')">
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

    <CreateTaskModal v-if="showCreateModal" @close="showCreateModal = false" @created="handleTaskCreated" />
    <UploadDatasetModal v-if="showUploadModal" :task="uploadTarget" @close="showUploadModal = false" @uploaded="handleDatasetUploaded" />
    <FieldSignModal v-if="showFieldSignModal" :task="fieldSignTarget" @close="showFieldSignModal = false" @signed="handleFieldSigned" />
    <RechargeModal v-if="showRechargeModal" :current-balance="user?.balance || 0" @close="showRechargeModal = false" @recharged="handleRecharged" />
    <HelpGuideModal v-if="showHelpModal" @close="showHelpModal = false" />
    <AdminSwitchModal v-if="showAdminSwitchModal" @close="showAdminSwitchModal = false" />
    <ProfileModal v-if="showProfileModal" @close="showProfileModal = false" />
  </div>
</template>

<style>
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #e2e8f0; }
::-webkit-scrollbar-thumb { background: #94a3b8; border-radius: 0px; }
</style>
