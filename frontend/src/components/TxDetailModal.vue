<script setup>
const props = defineProps({
  tx: { type: Object, default: null }
})

const emit = defineEmits(['close'])
import { useToastStore } from '@/stores/toast'
const toast = useToastStore()

function formatBlockNumber(num) {
  if (!num && num !== 0) return '-'
  return '#' + num.toLocaleString()
}
</script>

<template>
  <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-sm shadow-xl w-full max-w-2xl overflow-hidden flex flex-col border border-slate-300 max-h-[90vh]">
      <!-- 头部 -->
      <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center shrink-0">
        <h2 class="text-sm font-bold text-slate-800">交易详情</h2>
        <button @click="emit('close')" class="text-slate-400 hover:text-slate-700">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>

      <!-- 内容 -->
      <div class="p-6 space-y-4 bg-white overflow-y-auto flex-1">
        <!-- 交易哈希 -->
        <div class="bg-slate-50 border border-slate-200 rounded-sm p-4">
          <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">交易哈希</div>
          <div class="text-sm font-mono text-slate-800 break-all">
            {{ tx?.tx_hash || '-' }}
          </div>
        </div>

        <!-- 区块高度与时间戳 -->
        <div class="grid grid-cols-2 gap-4">
          <div class="bg-slate-50 border border-slate-200 rounded-sm p-3">
            <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">区块高度</div>
            <div class="text-sm font-bold text-slate-800 font-mono">
              {{ formatBlockNumber(tx?.block_number) }}
            </div>
          </div>
          <div class="bg-slate-50 border border-slate-200 rounded-sm p-3">
            <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">时间戳</div>
            <div class="text-sm font-bold text-slate-800">
              {{ tx?.created_at || '-' }}
            </div>
          </div>
        </div>

        <!-- 交易内容 -->
        <div class="bg-slate-50 border border-slate-200 rounded-sm p-4">
          <div class="text-xs text-slate-500 uppercase tracking-wider mb-2">交易内容 (Input Data)</div>
          <div class="bg-white border border-slate-200 rounded-sm p-3 font-mono text-xs text-slate-700 break-all leading-relaxed">
            <div>Function: {{ tx?.function_name || 'submitAuditReport(string taskHash, uint8 result, string reportIPFS)' }}</div>
            <div>TaskHash: {{ tx?.task_id || '-' }}</div>
            <div>Result: {{ tx?.result || 'PASS (1)' }}</div>
            <div>ReportIPFS: {{ tx?.report_ipfs || 'QmX7bR9s...3vK5' }}</div>
          </div>
        </div>

        <!-- Gas消耗 -->
        <div class="bg-slate-50 border border-slate-200 rounded-sm p-4">
          <div class="text-xs text-slate-500 uppercase tracking-wider mb-1">Gas 消耗</div>
          <div class="text-sm font-bold text-slate-800 font-mono">
            {{ tx?.gas_used ? tx.gas_used.toLocaleString() : '125,432' }}
          </div>
        </div>
      </div>

      <!-- 底部按钮 -->
      <div class="px-6 py-4 border-t border-slate-200 bg-slate-50 flex justify-end gap-3 shrink-0">
        <button
          @click="emit('close')"
          class="px-5 py-2 text-xs font-bold text-slate-600 hover:text-slate-900 bg-white border border-slate-300 rounded-sm"
        >
          关闭
        </button>
        <button
          class="px-5 py-2 text-xs font-bold text-white bg-[#0f172a] hover:bg-slate-800 rounded-sm"
          @click="toast.success('在 FISCO BCOS 浏览器中查看完整交易')"
        >
          查看原始交易
        </button>
      </div>
    </div>
  </div>
</template>
