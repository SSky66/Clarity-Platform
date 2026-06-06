<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { listChainEventsV2, getChainEventDetail, getChainStats } from '@/api/chain'
import { getMe } from '@/api/auth'
import { useToastStore } from '@/stores/toast'
import AppHeader from '@/components/AppHeader.vue'
import Sidebar from '@/components/Sidebar.vue'
import RechargeModal from '@/components/RechargeModal.vue'
import TxDetailModal from '@/components/TxDetailModal.vue'
import HelpGuideModal from '@/components/HelpGuideModal.vue'
import AdminSwitchModal from '@/components/AdminSwitchModal.vue'

const router = useRouter()
const authStore = useAuthStore()
const toast = useToastStore()

const user = computed(() => authStore.user)
const events = ref([])
const totalCount = ref(0)

// 链上统计
const chainStats = ref({
  block_height: null,
  total_transactions: null,
  active_nodes: null,
  total_onchain_records: 0,
  connected: false
})

const searchType = ref('project')
const searchQuery = ref('')
const filterType = ref('')

const page = ref(1)
const limit = ref(10)

const showRechargeModal = ref(false)
const showTxDetailModal = ref(false)
const showHelpModal = ref(false)
const showAdminSwitchModal = ref(false)
const selectedTx = ref(null)

const searchPlaceholder = ref('输入项目ID，例如：0x2b4C...7a99')
const searchTip = ref('支持模糊查询，输入完整的0x开头哈希或项目ID')

function updateSearchHint() {
  if (searchType.value === 'project') {
    searchPlaceholder.value = '输入项目ID，例如：0x2b4C...7a99'
    searchTip.value = '支持模糊查询，输入完整的0x开头项目ID'
  } else if (searchType.value === 'tx') {
    searchPlaceholder.value = '输入交易哈希，例如：0x7a3b...9f12'
    searchTip.value = '支持模糊查询，输入完整的0x开头交易哈希'
  } else if (searchType.value === 'block') {
    searchPlaceholder.value = '输入区块高度，例如：4291205'
    searchTip.value = '输入数字区块高度'
  }
}


async function fetchEvents() {
  try {
    const params = { page: page.value, limit: limit.value }
    if (filterType.value) {
      params.event_type = filterType.value
    }
    const res = await listChainEventsV2(params)
    events.value = res || []
  } catch (e) {
    console.error('获取链上事件失败', e)
    toast.error('获取链上事件失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function performSearch() {
  if (!searchQuery.value.trim()) {
    toast.error('请输入查询内容')
    return
  }
  try {
    const params = { page: 1, limit: limit.value }
    if (searchType.value === 'project') {
      params.task_id = searchQuery.value.trim()
    } else if (searchType.value === 'tx') {
      params.tx_hash = searchQuery.value.trim()
    } else if (searchType.value === 'block') {
      params.block_number = searchQuery.value.trim()
    }
    const res = await listChainEventsV2(params)
    events.value = res || []
    page.value = 1
  } catch (e) {
    console.error('查询失败', e)
    toast.error('查询失败: ' + (e.response?.data?.detail || e.message))
  }
}

function handleSearchKeydown(e) {
  if (e.key === 'Enter') {
    performSearch()
  }
}

function prevPage() {
  if (page.value > 1) {
    page.value--
    fetchEvents()
  }
}

function nextPage() {
  page.value++
  fetchEvents()
}

function openTxDetail(event) {
  selectedTx.value = event
  showTxDetailModal.value = true
}

function goToDashboard(section) {
  const role = authStore.userRole
  let path = '/manufacturer'
  if (role === 'SUPPLIER') {
    path = '/supplier'
  } else if (role === 'AUDITOR') {
    path = '/auditor'
  } else if (role === 'ADMIN') {
    path = '/admin'
  }
  // 带上目标 section，让 Dashboard 直接切换到对应页面
  if (section && section !== 'project') {
    path += '?section=' + section
  }
  router.push(path)
}

function handleHeaderNav(section) {
  if (section === 'blockchain') {
    return
  }
  goToDashboard(section)
}

function handleRecharged() {
  showRechargeModal.value = false
}

async function fetchUser() {
  try {
    const res = await getMe()
    authStore.updateUser(res)
  } catch (e) {
    console.error('获取用户信息失败', e)
  }
}

function logout() {
  authStore.logout()
  router.push('/login')
}

async function fetchChainStats() {
  try {
    const res = await getChainStats()
    chainStats.value = res
    totalCount.value = res.total_onchain_records || 0
  } catch (e) {
    console.error('获取链上统计失败', e)
  }
}

onMounted(() => {
  fetchEvents()
  fetchChainStats()
})
</script>

<template>
  <div class="h-screen flex flex-col overflow-hidden selection:bg-slate-200 selection:text-slate-900" style="font-family: 'Inter', -apple-system, sans-serif; background-color: #f1f5f9; color: #0f172a;">
    <AppHeader
      current-section="blockchain"
      @switch-section="handleHeaderNav"
      @logout="logout"
      @show-help="showHelpModal = true"
      @show-admin-switch="showAdminSwitchModal = true"
    />

    <div class="flex-1 flex overflow-hidden">
      <Sidebar
        v-if="authStore.userRole !== 'ADMIN'"
        :user="user"
        current-section="blockchain"
        :role="authStore.userRole || 'MANUFACTURER'"
        @switch-section="goToDashboard"
        @recharge="showRechargeModal = true"
        @wallet-assigned="fetchUser"
      />

      <main class="flex-1 overflow-y-auto bg-slate-100 p-4 md:p-8">
        <!-- 页面标题 -->
        <div class="mb-6">
          <h2 class="text-lg font-bold text-slate-800">区块链浏览器</h2>
          <p class="text-sm text-slate-600 mt-1">
            查询 Clarity 澄澈系统在 FISCO BCOS 联盟链上的交易记录与链上存证
          </p>
        </div>

        <!-- 链上概览卡片 -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-6 mb-6">
          <div class="bg-white border border-slate-200 rounded-sm shadow-sm p-6">
            <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">当前区块高度</div>
            <div class="text-xl font-bold text-slate-800 font-mono">
              {{ chainStats.block_height ? '#' + chainStats.block_height.toLocaleString() : '--' }}
            </div>
            <div class="text-xs text-slate-600 mt-2 flex items-center gap-1">
              <span
                class="w-1.5 h-1.5 rounded-full mr-1"
                :class="chainStats.connected ? 'bg-emerald-500' : 'bg-rose-500'"
              ></span>
              {{ chainStats.connected ? '区块链网络正常' : '未接入区块链' }}
            </div>
          </div>

          <div class="bg-white border border-slate-200 rounded-sm shadow-sm p-6">
            <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">总交易笔数</div>
            <div class="text-xl font-bold text-slate-800">{{ chainStats.total_onchain_records?.toLocaleString() || '--' }}</div>
            <div class="text-xs text-slate-500 mt-2">Clarity 平台累计上链交易</div>
          </div>

          <div class="bg-white border border-slate-200 rounded-sm shadow-sm p-6">
            <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">共识节点数量</div>
            <div class="text-xl font-bold text-slate-800">{{ chainStats.active_nodes || '--' }}</div>
            <div class="text-xs text-slate-500 mt-2">FISCO BCOS 联盟链共识节点</div>
          </div>

          <div class="bg-white border border-slate-200 rounded-sm shadow-sm p-6">
            <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">链上存证数量</div>
            <div class="text-xl font-bold text-slate-800">{{ chainStats.total_onchain_records?.toLocaleString() || '--' }}</div>
            <div class="text-xs text-slate-500 mt-2">Clarity 审计报告链上存证</div>
          </div>
        </div>

        <!-- 搜索区 -->
        <div class="bg-white border border-slate-200 rounded-sm shadow-sm p-6 mb-6">
          <div class="flex gap-4 mb-4">
            <div class="flex-1">
              <label class="block text-xs font-bold text-slate-700 mb-2">查询类型</label>
              <select
                v-model="searchType"
                class="w-full border border-slate-300 rounded-sm px-3 py-2 text-sm bg-white focus:outline-none focus:border-slate-800"
                @change="updateSearchHint"
              >
                <option value="project">项目 ID (Task Hash)</option>
                <option value="tx">交易哈希 (Tx Hash)</option>
                <option value="block">区块高度 (Block Number)</option>
              </select>
            </div>
            <div class="flex-[3]">
              <label class="block text-xs font-bold text-slate-700 mb-2">查询内容</label>
              <div class="flex gap-2">
                <input
                  v-model="searchQuery"
                  type="text"
                  :placeholder="searchPlaceholder"
                  class="flex-1 border border-slate-300 rounded-sm px-4 py-2 text-sm font-mono bg-white transition-all focus:outline-none focus:border-slate-800"
                  @keydown="handleSearchKeydown"
                />
                <button
                  @click="performSearch"
                  class="px-6 py-2 bg-[#0f172a] hover:bg-slate-800 text-white text-sm font-bold rounded-sm transition-colors"
                >
                  查询
                </button>
              </div>
            </div>
          </div>
          <div class="text-xs text-slate-500 flex items-center gap-2">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>
            <span>{{ searchTip }}</span>
          </div>
        </div>

        <!-- 交易列表 -->
        <div class="bg-white border border-slate-200 rounded-sm shadow-sm overflow-hidden">
          <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
            <h3 class="text-sm font-bold text-slate-800">最近上链交易</h3>
            <div class="flex gap-2">
              <select
                v-model="filterType"
                class="text-xs border border-slate-300 rounded-sm px-2 py-1 text-slate-700 outline-none bg-white"
                @change="fetchEvents"
              >
                <option value="">全部类型</option>
                <option value="STAKE">资金质押</option>
                <option value="UPLOAD">文件上传</option>
                <option value="AUDIT">审计完成</option>
                <option value="SETTLE">资金结算</option>
                <option value="DEPLOY">合约部署</option>
              </select>
            </div>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse">
              <thead>
                <tr class="bg-slate-100 text-slate-600 text-xs border-b border-slate-200">
                  <th class="px-6 py-3 font-medium">交易哈希 (Tx Hash)</th>
                  <th class="px-6 py-3 font-medium">区块高度</th>
                  <th class="px-6 py-3 font-medium">类型</th>
                  <th class="px-6 py-3 font-medium">项目ID</th>
                  <th class="px-6 py-3 font-medium">时间</th>
                  <th class="px-6 py-3 font-medium text-right">操作</th>
                </tr>
              </thead>
              <tbody class="text-sm divide-y divide-slate-200 bg-white">
                <tr
                  v-for="event in events"
                  :key="event.id || event.tx_hash"
                  class="hover:bg-slate-50 transition-colors"
                >
                  <td class="px-6 py-4">
                    <span class="font-mono text-xs text-slate-700">{{ event.tx_hash || '-' }}</span>
                  </td>
                  <td class="px-6 py-4 text-xs font-mono text-slate-600">
                    #{{ event.block_number ? event.block_number.toLocaleString() : '-' }}
                  </td>
                  <td class="px-6 py-4">
                    <span class="text-xs font-bold text-slate-700 bg-slate-100 px-2 py-1 rounded-sm border border-slate-300">
                      {{ event.event_type_display || event.event_type || '-' }}
                    </span>
                  </td>
                  <td class="px-6 py-4 font-mono text-xs text-slate-700">
                    {{ event.task_id || '-' }}
                  </td>
                  <td class="px-6 py-4 text-xs text-slate-600">
                    {{ event.created_at || '-' }}
                  </td>
                  <td class="px-6 py-4 text-right">
                    <button
                      @click="openTxDetail(event)"
                      class="text-slate-700 bg-slate-100 border border-slate-300 hover:bg-slate-200 font-bold text-xs px-3 py-1.5 rounded-sm transition-colors"
                    >
                      查看详情
                    </button>
                  </td>
                </tr>
                <tr v-if="events.length === 0">
                  <td colspan="6" class="px-6 py-8 text-center text-sm text-slate-500">
                    暂无交易记录
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="px-6 py-3 border-t border-slate-200 bg-slate-50 flex justify-between items-center">
            <span class="text-xs text-slate-500">
              显示 {{ events.length > 0 ? (page - 1) * limit + 1 : 0 }}-{{ (page - 1) * limit + events.length }} 条，共 {{ totalCount }} 条记录
            </span>
            <div class="flex gap-2">
              <button
                @click="prevPage"
                :disabled="page <= 1"
                class="px-3 py-1 text-xs font-bold text-slate-600 bg-white border border-slate-300 rounded-sm hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                上一页
              </button>
              <button
                @click="nextPage"
                class="px-3 py-1 text-xs font-bold text-slate-600 bg-white border border-slate-300 rounded-sm hover:bg-slate-50"
              >
                下一页
              </button>
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
    <TxDetailModal
      v-if="showTxDetailModal"
      :tx="selectedTx"
      @close="showTxDetailModal = false"
    />
    <HelpGuideModal v-if="showHelpModal" @close="showHelpModal = false" />
    <AdminSwitchModal v-if="showAdminSwitchModal" @close="showAdminSwitchModal = false" />
  </div>
</template>

<style>
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #e2e8f0; }
::-webkit-scrollbar-thumb { background: #94a3b8; border-radius: 0px; }
</style>
