<script setup>
import { ref, computed } from 'vue'
import { useToastStore } from '@/stores/toast'
import { recharge } from '@/api/auth'

const props = defineProps({
  currentBalance: { type: Number, default: 0 }
})

const emit = defineEmits(['close', 'recharged'])
const toast = useToastStore()

const amount = ref('')

const afterBalance = computed(() => {
  const val = parseInt(amount.value || 0)
  return props.currentBalance + val
})

function fillAmount(val) {
  amount.value = String(val)
}

async function handleRecharge() {
  const val = parseInt(amount.value)
  if (!val || val <= 0) {
    toast.error('请输入有效金额')
    return
  }
  try {
    // 这里还是常量Mock上去的，记得改
    await recharge(val)
    toast.success(`充值成功！充值金额: ${val} points，交易已上链，区块高度: #4,291,089`)
    emit('recharged')
  } catch (e) {
    console.error('充值失败', e)
    toast.error('充值失败: ' + (e.response?.data?.detail || e.message))
  }
}
</script>

<template>
  <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-sm shadow-xl w-full max-w-md overflow-hidden flex flex-col border border-slate-300">
      <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
        <h2 class="text-sm font-bold text-slate-800">链上资金充值</h2>
        <button @click="emit('close')" class="text-slate-400 hover:text-slate-700">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>

      <div class="p-6 space-y-5 bg-white">
        <div>
          <label class="block text-xs font-bold text-slate-700 mb-2">充值金额</label>
          <div class="relative">
            <input
              v-model="amount"
              type="number"
              placeholder="输入金额数量"
              class="w-full border border-slate-300 rounded-sm px-3 py-2 text-sm focus:outline-none focus:border-slate-800 placeholder-slate-400 font-mono"
            />
            <span class="absolute right-3 top-2 text-xs text-slate-500 font-bold">points</span>
          </div>
        </div>

        <div class="grid grid-cols-3 gap-3">
          <button
            v-for="val in [1000, 5000, 10000]"
            :key="val"
            class="py-2 border border-slate-300 rounded-sm text-xs font-bold text-slate-700 hover:bg-slate-50"
            @click="fillAmount(val)"
          >
            {{ val.toLocaleString() }}
          </button>
        </div>

        <div class="bg-slate-50 border border-slate-200 rounded-sm p-3">
          <div class="flex justify-between text-xs mb-1">
            <span class="text-slate-500">当前余额</span>
            <span class="font-mono font-bold text-slate-800">{{ props.currentBalance.toLocaleString() }} points</span>
          </div>
          <div class="flex justify-between text-xs">
            <span class="text-slate-500">充值后余额</span>
            <span class="font-mono font-bold text-slate-800">{{ afterBalance.toLocaleString() }} points</span>
          </div>
        </div>
      </div>

      <div class="px-6 py-4 border-t border-slate-200 bg-slate-50 flex justify-end gap-3">
        <button
          @click="emit('close')"
          class="px-5 py-2 text-xs font-bold text-slate-600 hover:text-slate-900 bg-white border border-slate-300 rounded-sm"
        >
          取消
        </button>
        <button
          @click="handleRecharge"
          class="px-5 py-2 text-xs font-bold text-white bg-[#0f172a] hover:bg-slate-800 rounded-sm"
        >
          确认充值
        </button>
      </div>
    </div>
  </div>
</template>
