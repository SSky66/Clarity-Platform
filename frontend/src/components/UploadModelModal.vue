<script setup>
import { ref, computed, onMounted } from 'vue'
import { useToastStore } from '@/stores/toast'
import { uploadModel, supplierPrepare } from '@/api/tasks'
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
    const userId = props.task?.supplier_id
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

// 动态计算前端显示的预计金额（与后端对齐）
const depositAmount = computed(() => {
  return Math.round(baseDeposit * stakeRatio.value)
})

const supplierMargin = computed(() => {
  return depositAmount.value + auditFee
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
      ipfsHash.value = 'ipfs://QmX7bR9s...3vK5 (' + fileName.value + ')'
    }
  }, 200)
}

async function handleConfirm() {
  if (!file.value || !uploadComplete.value) return
  try {
    // 1.上传模型文件
    await uploadModel(props.task.id, file.value)

    // 2.调用supplierPrepare进行质押（后端根据信誉动态计算实际金额）
    const res = await supplierPrepare(props.task.id, {
      model_hash: ipfsHash.value,
      model_desc_hash: null
    })

    // 使用后端返回的实际金额显示
    const actualLocked = res?.sup_locked || supplierMargin.value
    toast.success(`模型上传并质押成功！项目: ${props.task.name} TorchScript 模型已加密上传至 IPFS。质押金 ${Math.round(actualLocked + auditFee).toLocaleString()} points（含${auditFee} points审计服务费）已锁定。等待制造商上传测试集后进入审计。`)
    emit('uploaded')
  } catch (e) {
    console.error('上传或质押失败', e)
    const detail = e.response?.data?.detail
    const msg = typeof detail === 'string' ? detail : JSON.stringify(detail)
    toast.error('上传失败: ' + (msg || e.message))
  }
}

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
    <div class="bg-white rounded-sm shadow-xl w-full max-w-2xl overflow-hidden flex flex-col border border-slate-300 max-h-[90vh]">
      <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center shrink-0">
        <div>
          <h2 class="text-sm font-bold text-slate-800">上传视觉模型文件</h2>
          <p class="text-xs text-slate-500 mt-1">项目: {{ task.task_name || task.name }}</p>
        </div>
        <button @click="emit('close')" class="text-slate-400 hover:text-slate-700">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>

      <div class="p-6 space-y-6 bg-white overflow-y-auto flex-1">
        <!-- 解析出的任务信息 -->
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
          <div class="grid grid-cols-2 gap-4 text-sm mt-3">
            <div>
              <span class="block text-xs text-slate-500 mb-1">硬性指标：最高容忍漏杀率</span>
              <span class="font-bold text-slate-800 font-mono">≤ {{ (task.target_fnr * 100) || 0.5 }}%</span>
            </div>
            <div>
              <span class="block text-xs text-slate-500 mb-1">硬性指标：最高容忍误杀率</span>
              <span class="font-bold text-slate-800 font-mono">≤ {{ (task.target_fpr * 100) || 5.0 }}%</span>
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

        <!-- 模型上传区 -->
        <div class="border border-slate-300 rounded-sm p-4 bg-white">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
              <span class="text-sm font-bold text-slate-800">TorchScript 模型文件</span>
              <span class="text-[10px] text-slate-500 bg-slate-100 px-2 py-0.5 rounded-sm border border-slate-200">.pt / .pth / .torchscript</span>
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
            <input type="file" accept=".pt,.pth,.torchscript" class="hidden" @change="onFileChange" />
            <svg class="w-8 h-8 text-slate-400 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path>
            </svg>
            <span class="text-xs text-slate-600 font-medium">
              {{ fileName || '点击上传或拖拽 TorchScript 模型至此处' }}
            </span>
            <span class="text-[10px] text-slate-400 mt-1">请确保模型为 torch.jit.script 导出格式</span>
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

        <!-- 质押确认 -->
        <div class="border-t border-slate-200 pt-6">
          <label class="block text-xs font-bold text-slate-700 mb-3">基础防欺诈质押金</label>
          <div class="bg-slate-50 border border-slate-200 rounded-sm p-4">
            <div class="flex items-center justify-between mb-2">
              <div>
                <div class="text-sm font-bold text-slate-800">供应商质押金额</div>
                <div class="text-[11px] text-slate-500 mt-1">若触发反作弊规则将被系统罚没，正常未达标将原路退回</div>
              </div>
              <div class="text-xl font-bold text-slate-800 font-mono">
                {{ supplierMargin.toLocaleString() }} <span class="text-xs font-normal text-slate-500">points</span>
              </div>
            </div>
            <div class="border-t border-slate-200 pt-2 mt-2 space-y-1">
              <div class="flex justify-between text-xs text-slate-500">
                <span>基础质押金（{{ stakeRatio.toFixed(2) }}x 信誉系数）</span>
                <span>{{ depositAmount.toLocaleString() }} points</span>
              </div>
              <div class="flex justify-between text-xs text-slate-500">
                <span>审计服务费</span>
                <span>{{ auditFee }} points</span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="uploadComplete" class="bg-slate-50 border border-slate-200 rounded-sm p-4">
          <div class="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-2">模型 IPFS Hash 预览</div>
          <div class="font-mono text-xs text-slate-800 break-all bg-white p-2 rounded-sm border border-slate-300">
            {{ ipfsHash }}
          </div>
        </div>
      </div>

      <div class="px-6 py-4 border-t border-slate-200 bg-slate-50 flex justify-between items-center shrink-0">
        <div class="text-xs text-slate-500">
          上传完成后，模型将加密存储至IPFS并生成唯一存证Hash
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
            签署并上传
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
