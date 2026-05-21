<script setup>
import { ref } from 'vue'

const props = defineProps({
  task: { type: Object, default: null }
})

const emit = defineEmits(['close', 'dispatch'])

const selectedNode = ref('node1')

const gpuNodes = [
  {
    id: 'node1',
    name: 'NODE-GPU-01',
    spec: 'NVIDIA RTX 4060 | 状态: 闲置',
    status: 'available',
    statusLabel: '推荐可用',
    statusClass: 'bg-emerald-50 text-emerald-700 border-emerald-200'
  },
  {
    id: 'node2',
    name: 'NODE-GPU-02',
    spec: '暂未配置',
    status: 'unconfigured',
    statusLabel: '暂未配置',
    statusClass: 'bg-slate-100 text-slate-600 border-slate-200'
  }
]

function handleConfirm() {
  if (!props.task) return
  emit('dispatch', props.task.id)
}
</script>

<template>
  <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-sm shadow-xl w-full max-w-xl overflow-hidden flex flex-col border border-slate-300 max-h-[90vh]">
      <!-- 头部 -->
      <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center shrink-0">
        <h2 class="text-sm font-bold text-slate-800">分配计算任务</h2>
        <button @click="emit('close')" class="text-slate-400 hover:text-slate-700">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>

      <!-- 内容 -->
      <div class="p-6 space-y-6 bg-white overflow-y-auto flex-1">
        <!-- 项目信息 -->
        <div class="bg-slate-50 border border-slate-200 rounded-sm p-4">
          <div class="text-sm font-bold text-slate-800 mb-1">{{ task?.name || '3C 手机外壳划痕检测' }}</div>
          <div class="text-xs text-slate-500 font-mono mb-4">ID: {{ task?.id || '0x2b4C...7a99' }}</div>

          <div class="grid grid-cols-2 gap-4">
            <div class="bg-white p-3 border border-slate-200 rounded-sm">
              <span class="block text-[11px] text-slate-500 uppercase tracking-wider mb-1">验证集源</span>
              <span class="text-xs font-bold text-slate-800 font-mono truncate block" :title="task?.dataset_hash || 'ipfs://QmXp...2H8s'">
                {{ task?.dataset_hash || 'ipfs://QmXp...2H8s' }}
              </span>
            </div>
            <div class="bg-white p-3 border border-slate-200 rounded-sm">
              <span class="block text-[11px] text-slate-500 uppercase tracking-wider mb-1">模型源</span>
              <span class="text-xs font-bold text-slate-800 font-mono truncate block" :title="task?.model_hash || 'ipfs://QmYa...9P1c'">
                {{ task?.model_hash || 'ipfs://QmYa...9P1c' }}
              </span>
            </div>
          </div>
        </div>

        <!-- GPU 节点选择 -->
        <div>
          <label class="block text-xs font-bold text-slate-700 mb-3">选择本地执行物理节点</label>
          <div class="grid grid-cols-1 gap-3">
            <label
              v-for="node in gpuNodes"
              :key="node.id"
              class="relative cursor-pointer"
              :class="{ 'cursor-not-allowed': node.status === 'unconfigured' }"
            >
              <input
                v-model="selectedNode"
                type="radio"
                name="nodeSelect"
                :value="node.id"
                class="sr-only"
                :disabled="node.status === 'unconfigured'"
              />
              <div
                class="border rounded-sm p-4 h-full flex items-center justify-between transition-all"
                :class="[
                  node.status === 'unconfigured'
                    ? 'border-slate-300 opacity-50 cursor-not-allowed'
                    : selectedNode === node.id
                      ? 'border-[#0f172a] bg-[#f8fafc] shadow-[0_0_0_1px_#0f172a]'
                      : 'border-slate-300 hover:border-slate-400'
                ]"
              >
                <div>
                  <div class="font-bold text-slate-800 text-sm">{{ node.name }}</div>
                  <div class="text-xs text-slate-500 mt-1 font-mono">{{ node.spec }}</div>
                </div>
                <div
                  class="text-[10px] px-2 py-1 rounded-sm border"
                  :class="node.statusClass"
                >
                  {{ node.statusLabel }}
                </div>
              </div>
            </label>
          </div>
        </div>
      </div>

      <!-- 底部按钮 -->
      <div class="px-6 py-4 border-t border-slate-200 bg-slate-50 flex justify-end gap-3 shrink-0">
        <button
          @click="emit('close')"
          class="px-5 py-2 text-xs font-bold text-slate-600 hover:text-slate-900 bg-white border border-slate-300 rounded-sm"
        >
          取消
        </button>
        <button
          @click="handleConfirm"
          class="px-5 py-2 text-xs font-bold text-white bg-[#0f172a] hover:bg-slate-800 rounded-sm"
        >
          注入环境并执行
        </button>
      </div>
    </div>
  </div>
</template>
