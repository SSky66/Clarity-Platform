<script setup>
import { ref, computed, onMounted } from 'vue'
import { useToastStore } from '@/stores/toast'
import { uploadDataset, manufacturerPrepare } from '@/api/tasks'
import { getStakeRatio } from '@/api/auth'

const props = defineProps({
  task: { type: Object, required: true }
})

function formatHash(hash) {
  if (!hash || typeof hash !== 'string') return hash
  if (hash.startsWith('0x') && hash.length > 12) {
    return hash.slice(0, 6) + '...' + hash.slice(-4)
  }
  return hash
}

const emit = defineEmits(['close', 'uploaded'])
const toast = useToastStore()

const guaranteeMode = ref('high')
const file = ref(null)
const fileName = ref('')
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadComplete = ref(false)
const ipfsHash = ref('')
const stakeRatio = ref(1.5)  // 动态质押比例，默认150%
const userReputation = ref(70) // 用户信誉分

// 加载动态质押比例
async function loadStakeRatio() {
  try {
    const userId = props.task?.manufacturer_id
    if (!userId) return
    const res = await getStakeRatio(userId)
    if (res) {
      stakeRatio.value = res.stake_ratio || 1.5
      userReputation.value = res.reputation_score || 70
    }
  } catch (e) {
    console.error('获取质押比例失败', e)
  }
}

const baseDeposit = 1000
const auditFee = 50
const insuranceFee = 50

// 动态计算前端显示的预计金额（与后端对齐）
const depositAmount = computed(() => {
  return Math.round(baseDeposit * stakeRatio.value)
})

const totalFund = computed(() => {
  const deposit = depositAmount.value
  if (guaranteeMode.value === 'high') {
    // 全额保证金模式：1倍动态质押金与审计费（与后端对齐）
    return deposit + auditFee
  }
  // 保险模式：1倍动态质押金、审计费、保险费
  return deposit + auditFee + insuranceFee
})

const fundDetails = computed(() => {
  const deposit = depositAmount.value
  if (guaranteeMode.value === 'high') {
    return [
      { label: `基础质押金（${stakeRatio.value.toFixed(2)}x 信誉系数）`, value: `${deposit.toLocaleString()} points` },
      { label: '审计服务费', value: `${auditFee} points` }
    ]
  }
  return [
    { label: `基础质押金（${stakeRatio.value.toFixed(2)}x 信誉系数）`, value: `${deposit.toLocaleString()} points` },
    { label: '审计服务费', value: `${auditFee} points` },
    { label: '数据集保险', value: `${insuranceFee} points` }
  ]
})

function onFileChange(e) {
  const f = e.target.files?.[0]
  if (!f) return
  file.value = f
  fileName.value = f.name
  simulateUpload()
}

function simulateUpload() {
  uploading.value = true
  uploadProgress.value = 0
  uploadComplete.value = false

  const interval = setInterval(() => {
    uploadProgress.value += Math.random() * 15
    if (uploadProgress.value >= 100) {
      uploadProgress.value = 100
      clearInterval(interval)
      uploading.value = false
      uploadComplete.value = true
      ipfsHash.value = 'ipfs://QmX4zR7sK9bL3...8vK2 (' + fileName.value + ')'
    }
  }, 200)
}

async function handleConfirm() {
  if (!file.value || !uploadComplete.value) return
  try {
    await uploadDataset(props.task.id, file.value)
    // 后端根据用户信誉动态计算实际质押金额，前端只需传是否购买保险
    const res = await manufacturerPrepare(props.task.id, {
      purchase_insurance: guaranteeMode.value === 'insurance',
      test_set_hash: ipfsHash.value
    })
    // 使用后端返回的实际金额显示
    const actualLocked = res?.mfr_locked || totalFund.value
    toast.success(`数据上传成功！项目: ${props.task.name} 测试集压缩包已上传至IPFS。质押金 ${Math.round(actualLocked).toLocaleString()} points 已锁定（信誉系数 ${stakeRatio.value.toFixed(2)}x）。等待供应商上传模型后进入审计。`)
    emit('uploaded')
  } catch (e) {
    console.error('上传失败', e)
    toast.error('上传失败: ' + (e.response?.data?.detail || e.message))
  }
}

// 组件挂载时加载动态质押比例
onMounted(() => {
  loadStakeRatio()
})

function onDrop(e) {
  e.preventDefault()
  const f = e.dataTransfer.files?.[0]
  if (f) {
    file.value = f
    fileName.value = f.name
    simulateUpload()
  }
}
</script>

<template>
  <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-sm shadow-xl w-full max-w-2xl overflow-hidden flex flex-col border border-slate-300 max-h-[96vh]">
      <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center shrink-0">
        <div>
          <h2 class="text-sm font-bold text-slate-800">上传测试数据集</h2>
          <p class="text-xs text-slate-500 mt-1">项目: {{ task.task_name || task.name }}</p>
        </div>
        <button @click="emit('close')" class="text-slate-400 hover:text-slate-700">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>

      <div class="p-6 space-y-6 bg-white overflow-y-auto flex-1">
        <!-- 项目信息 -->
        <div class="bg-slate-50 border border-slate-200 rounded-sm p-4">
          <div class="flex items-center justify-between mb-3 border-b border-slate-200 pb-2">
            <div class="text-sm font-bold text-slate-800">模型验收标准确认</div>
            <div class="text-xs font-mono text-slate-500">{{ formatHash(task.task_hash) }}</div>
          </div>
          <!-- 项目描述 -->
          <div v-if="task.description" class="mb-3 pb-3 border-b border-slate-200">
            <span class="block text-xs text-slate-500 mb-1">项目描述</span>
            <span class="text-sm text-slate-700 leading-relaxed">{{ task.description }}</span>
          </div>
          <!-- 验收标准 -->
          <div class="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span class="block text-xs text-slate-500 mb-1">硬性指标：最高容忍漏杀率</span>
              <span class="font-bold text-slate-800 font-mono">≤ {{ ((task.target_fnr || 0.005) * 100).toFixed(1) }}%</span>
            </div>
            <div>
              <span class="block text-xs text-slate-500 mb-1">硬性指标：最高容忍误杀率</span>
              <span class="font-bold text-slate-800 font-mono">≤ {{ ((task.target_fpr || 0.05) * 100).toFixed(1) }}%</span>
            </div>
            <div>
              <span class="block text-xs text-slate-500 mb-1">协商指标：mAP@0.5</span>
              <span class="font-bold text-slate-800 font-mono">≥ {{ ((task.target_map || 0.85) * 100).toFixed(0) }}%</span>
            </div>
            <div>
              <span class="block text-xs text-slate-500 mb-1">协商指标：F1 Score</span>
              <span class="font-bold text-slate-800 font-mono">≥ {{ task.target_f1 || 0.8 }}</span>
            </div>
            <div>
              <span class="block text-xs text-slate-500 mb-1">物理约束：边缘端延迟</span>
              <span class="font-bold text-slate-800 font-mono">≤ {{ task.target_latency || 50 }} ms</span>
            </div>
            <div>
              <span class="block text-xs text-slate-500 mb-1">工作置信度阈值 (Conf)</span>
              <span class="font-bold text-slate-800 font-mono">{{ task.conf_threshold || 0.25 }}</span>
            </div>
            <div>
              <span class="block text-xs text-slate-500 mb-1">IoU 评估阈值</span>
              <span class="font-bold text-slate-800 font-mono">{{ task.iou_threshold || 0.50 }}</span>
            </div>
          </div>
        </div>

        <div class="bg-slate-50 border border-slate-200 rounded-sm p-4">
          <div class="flex items-start gap-3">
            <svg class="w-4 h-4 text-slate-600 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>
            <div>
              <div class="text-xs font-bold text-slate-800 mb-1">数据格式要求</div>
              <div class="text-xs text-slate-600 leading-relaxed">
                请将图像测试集（需区分无缺陷图与有缺陷图）与 YAML 标注文件统一打包为一个 `.zip` 压缩包上传。系统将在链下沙盒中解压并执行三步审计。
              </div>
            </div>
          </div>
        </div>

        <div class="space-y-4">
          <div class="border border-slate-300 rounded-sm p-4 bg-white">
            <div class="flex items-center justify-between mb-3">
              <div class="flex items-center gap-2">
                <span class="text-sm font-bold text-slate-800">测试数据集压缩包</span>
                <span class="text-[10px] text-slate-500 bg-slate-100 px-2 py-0.5 rounded-sm border border-slate-200">.zip / .tar.gz</span>
              </div>
              <span class="text-xs" :class="uploadComplete ? 'text-blue-600 font-bold' : 'text-slate-400'">
                {{ uploadComplete ? '已完成' : uploading ? '上传中...' : '等待上传' }}
              </span>
            </div>
            <label
              class="border border-dashed border-slate-300 rounded-sm p-8 bg-slate-50 flex flex-col items-center justify-center cursor-pointer hover:bg-slate-100 transition-colors"
              @dragover.prevent
              @drop="onDrop"
            >
              <input type="file" accept=".zip,.tar.gz" class="hidden" @change="onFileChange" />
              <svg class="w-8 h-8 text-slate-400 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path>
              </svg>
              <span class="text-xs text-slate-600 font-medium">
                {{ fileName || '点击上传或拖拽压缩包至此' }}
              </span>
              <span class="text-[10px] text-slate-400 mt-1">需包含: 带标签测试集、对照集及配置 YAML</span>
            </label>
            <div v-if="uploading || uploadComplete" class="mt-4">
              <div class="flex justify-between text-[10px] text-slate-600 mb-1">
                <span>加密并上传至 IPFS...</span>
                <span>{{ Math.round(uploadProgress) }}%</span>
              </div>
              <div class="w-full bg-slate-200 rounded-sm h-1.5">
                <div
                  class="bg-blue-600 h-1.5 rounded-sm transition-[width] duration-300 ease-out"
                  :style="{ width: uploadProgress + '%' }"
                ></div>
              </div>
            </div>
          </div>
        </div>

        <div class="border-t border-slate-200 pt-6">
          <label class="block text-xs font-bold text-slate-700 mb-3">数据担保方式</label>
          <div class="grid grid-cols-2 gap-4 mb-4">
            <label class="relative cursor-pointer">
              <input v-model="guaranteeMode" type="radio" value="high" class="sr-only peer" />
              <div
                class="border border-slate-300 rounded-sm p-4 h-full flex items-center justify-between peer-checked:border-[#0f172a] peer-checked:bg-slate-50 peer-checked:shadow-[0_0_0_1px_#0f172a]"
              >
                <div class="font-bold text-slate-800 text-sm">全额保证金</div>
                <div class="text-xs text-slate-500">质押 3.0x 基础金</div>
              </div>
            </label>
            <label class="relative cursor-pointer">
              <input v-model="guaranteeMode" type="radio" value="insurance" class="sr-only peer" />
              <div
                class="border border-slate-300 rounded-sm p-4 h-full flex items-center justify-between peer-checked:border-[#0f172a] peer-checked:bg-slate-50 peer-checked:shadow-[0_0_0_1px_#0f172a]"
              >
                <div class="font-bold text-slate-800 text-sm">协会保险</div>
                <div class="text-xs text-slate-500 font-bold text-slate-800">附加保费: 50 points</div>
              </div>
            </label>
          </div>

          <div class="bg-slate-50 border border-slate-200 rounded-sm p-4">
            <div class="flex items-center justify-between mb-2">
              <div>
                <div class="text-sm font-bold text-slate-800">预计锁定资金</div>
                <div class="text-[11px] text-slate-500 mt-1">资金将锁定至项目完结，正常履约后全额退还</div>
              </div>
              <div class="text-xl font-bold text-slate-800 font-mono">
                {{ totalFund.toLocaleString() }} <span class="text-xs font-normal text-slate-500">points</span>
              </div>
            </div>
            <div class="border-t border-slate-200 pt-2 mt-2 space-y-1">
              <div v-for="(item, idx) in fundDetails" :key="idx" class="flex justify-between text-xs text-slate-500">
                <span>{{ item.label }}：{{ item.value }}</span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="uploadComplete" class="bg-slate-50 border border-slate-200 rounded-sm p-4">
          <div class="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-2">数据集 IPFS Hash 预览</div>
          <div class="font-mono text-xs text-slate-800 break-all bg-white p-2 rounded-sm border border-slate-300">
            {{ ipfsHash }}
          </div>
        </div>
      </div>

      <div class="px-6 py-4 border-t border-slate-200 bg-slate-50 flex justify-between items-center shrink-0">
        <div class="text-xs text-slate-500">
          上传完成后，数据将加密存储至IPFS并生成唯一存证Hash
        </div>
        <div class="flex gap-3">
          <button
            @click="emit('close')"
            class="px-5 py-2 text-xs font-bold text-slate-600 hover:text-slate-900 bg-white border border-slate-300 rounded-sm"
          >
            取消
          </button>
          <button
            @click="handleConfirm"
            :disabled="!uploadComplete"
            class="px-5 py-2 text-xs font-bold text-white rounded-sm"
            :class="uploadComplete ? 'bg-[#0f172a] hover:bg-slate-800' : 'bg-slate-400 cursor-not-allowed'"
          >
            确认上传并质押
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
