<script setup>
import { reactive } from 'vue'
import { useToastStore } from '@/stores/toast'
import { createTask } from '@/api/tasks'

const emit = defineEmits(['close', 'created'])
const toast = useToastStore()

const form = reactive({
  task_name: '',
  target_fnr: 0.5,
  target_fpr: 0.05,
  target_map: 0.85,
  target_f1: 0.80,
  target_latency: 50,
  conf_threshold: 0.25,
  iou_threshold: 0.50,

  description: ''
})



async function handleSubmit() {
  try {
    const payload = {
      task_name: form.task_name,
      target_fnr: parseFloat(form.target_fnr) / 100,
      target_fpr: parseFloat(form.target_fpr) / 100,
      target_map: parseFloat(form.target_map) / 100,
      target_f1: parseFloat(form.target_f1),
      target_latency: parseInt(form.target_latency),
      conf_threshold: parseFloat(form.conf_threshold),
      iou_threshold: parseFloat(form.iou_threshold),

      description: form.description
    }
    await createTask(payload)
    emit('created')
  } catch (e) {
    console.error('创建项目失败', e)
    const detail = e.response?.data?.detail
    let msg = e.message
    if (detail) {
      if (Array.isArray(detail)) {
        msg = detail.map(d => typeof d === 'string' ? d : (d.msg || d.message || JSON.stringify(d))).join(', ')
      } else if (typeof detail === 'string') {
        msg = detail
      } else {
        msg = JSON.stringify(detail)
      }
    }
    toast.error('创建项目失败: ' + msg)
  }
}
</script>

<template>
  <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-sm shadow-xl w-full max-w-2xl overflow-hidden flex flex-col border border-slate-300 max-h-[90vh]">
      <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center shrink-0">
        <h2 class="text-sm font-bold text-slate-800">新建审计项目</h2>
        <button @click="emit('close')" class="text-slate-400 hover:text-slate-700">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>

      <div class="p-6 space-y-6 bg-white overflow-y-auto flex-1">
        <div>
          <label class="block text-xs font-bold text-slate-700 mb-2">项目名称</label>
          <input
            v-model="form.task_name"
            type="text"
            placeholder="输入项目名称"
            class="w-full border border-slate-300 rounded-sm px-3 py-2 text-sm focus:outline-none focus:border-slate-800 placeholder-slate-400"
          />
        </div>

        <div class="space-y-4">
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-2">硬性审计指标</label>
            <div class="grid grid-cols-2 gap-4">
              <div class="border border-slate-300 rounded-sm bg-white flex items-stretch overflow-hidden h-11">
                <div class="bg-slate-50 w-28 flex items-center justify-center border-r border-slate-300 shrink-0" title="False Negative Rate">
                  <span class="text-slate-600 font-bold text-xs tracking-wider">最高容忍漏杀率</span>
                </div>
                <input
                  v-model.number="form.target_fnr"
                  type="number"
                  min="0"
                  max="5"
                  step="0.1"
                  class="flex-1 bg-transparent px-4 text-sm text-slate-800 focus:outline-none font-mono"
                />
                <div class="bg-slate-50 w-10 flex items-center justify-center border-l border-slate-300 shrink-0">
                  <span class="text-slate-500 text-xs font-bold">%</span>
                </div>
              </div>
              <div class="border border-slate-300 rounded-sm bg-white flex items-stretch overflow-hidden h-11">
                <div class="bg-slate-50 w-28 flex items-center justify-center border-r border-slate-300 shrink-0" title="False Positive Rate">
                  <span class="text-slate-600 font-bold text-xs tracking-wider">最高容忍误杀率</span>
                </div>
                <input
                  v-model.number="form.target_fpr"
                  type="number"
                  min="0"
                  max="20"
                  step="0.1"
                  class="flex-1 bg-transparent px-4 text-sm text-slate-800 focus:outline-none font-mono"
                />
                <div class="bg-slate-50 w-10 flex items-center justify-center border-l border-slate-300 shrink-0">
                  <span class="text-slate-500 text-xs font-bold">%</span>
                </div>
              </div>
            </div>
          </div>

          <div class="pt-2">
            <label class="block text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-2">协商参考指标</label>
            <div class="grid grid-cols-2 gap-4">
              <div class="border border-slate-200 rounded-sm bg-slate-50 flex items-stretch overflow-hidden h-9">
                <div class="bg-slate-100 w-20 flex items-center justify-center border-r border-slate-200 shrink-0">
                  <span class="text-slate-500 font-bold text-[10px] tracking-wider">mAP@0.5</span>
                </div>
                <input
                  v-model.number="form.target_map"
                  type="number"
                  min="50"
                  max="99"
                  class="flex-1 bg-transparent px-3 text-xs text-slate-600 focus:outline-none font-mono"
                />
                <div class="bg-slate-100 w-8 flex items-center justify-center border-l border-slate-200 shrink-0">
                  <span class="text-slate-400 text-[10px] font-bold">%</span>
                </div>
              </div>
              <div class="border border-slate-200 rounded-sm bg-slate-50 flex items-stretch overflow-hidden h-9">
                <div class="bg-slate-100 w-20 flex items-center justify-center border-r border-slate-200 shrink-0">
                  <span class="text-slate-500 font-bold text-[10px] tracking-wider">F1 Score</span>
                </div>
                <input
                  v-model.number="form.target_f1"
                  type="number"
                  min="0.5"
                  max="0.99"
                  step="0.01"
                  class="flex-1 bg-transparent px-3 text-xs text-slate-600 focus:outline-none font-mono"
                />
              </div>
            </div>
          </div>

          <div class="pt-2">
            <label class="block text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-2">模型评估阈值参数</label>
            <div class="grid grid-cols-2 gap-4">
              <div class="border border-slate-200 rounded-sm bg-slate-50 flex items-stretch overflow-hidden h-9">
                <div class="bg-slate-100 w-28 flex items-center justify-center border-r border-slate-200 shrink-0">
                  <span class="text-slate-500 font-bold text-[10px] tracking-wider">工作置信度 (Conf)</span>
                </div>
                <input
                  v-model.number="form.conf_threshold"
                  type="number"
                  min="0.1"
                  max="0.99"
                  step="0.01"
                  class="flex-1 bg-transparent px-3 text-xs text-slate-600 focus:outline-none font-mono"
                />
              </div>
              <div class="border border-slate-200 rounded-sm bg-slate-50 flex items-stretch overflow-hidden h-9">
                <div class="bg-slate-100 w-28 flex items-center justify-center border-r border-slate-200 shrink-0">
                  <span class="text-slate-500 font-bold text-[10px] tracking-wider">IoU 评估阈值</span>
                </div>
                <input
                  v-model.number="form.iou_threshold"
                  type="number"
                  min="0.1"
                  max="0.99"
                  step="0.01"
                  class="flex-1 bg-transparent px-3 text-xs text-slate-600 focus:outline-none font-mono"
                />
              </div>
            </div>
          </div>
        </div>

        <div class="grid grid-cols-2 gap-6">
          <div class="space-y-4">
            <label class="block text-xs font-bold text-slate-700 mb-2">物理约束</label>
            <div class="border border-slate-300 rounded-sm bg-white flex items-stretch overflow-hidden h-11">
              <div class="bg-slate-50 w-32 flex items-center justify-center border-r border-slate-300 shrink-0">
                <span class="text-slate-600 font-bold text-xs tracking-wider text-center leading-tight">
                  最大延迟<br><span class="text-[10px] font-normal text-slate-400">供审计参考</span>
                </span>
              </div>
              <input
                v-model.number="form.target_latency"
                type="number"
                min="10"
                max="500"
                step="10"
                class="flex-1 bg-transparent px-4 text-sm text-slate-800 focus:outline-none font-mono"
              />
              <div class="bg-slate-50 w-12 flex items-center justify-center border-l border-slate-300 shrink-0">
                <span class="text-slate-500 text-xs font-bold">ms</span>
              </div>
            </div>
          </div>

          <div class="space-y-4">
            <label class="block text-xs font-bold text-slate-700 mb-2">项目说明</label>
            <textarea
              v-model="form.description"
              placeholder="输入项目详细描述（可选）"
              class="w-full h-[calc(100%-1.5rem)] border border-slate-300 rounded-sm px-3 py-2 text-sm focus:outline-none focus:border-slate-800 placeholder-slate-400 resize-none"
            ></textarea>
          </div>
        </div>
      </div>

      <div class="px-6 py-4 border-t border-slate-200 bg-slate-50 flex justify-end gap-3 shrink-0">
        <button
          @click="emit('close')"
          class="px-5 py-2 text-xs font-bold text-slate-600 hover:text-slate-900 bg-white border border-slate-300 rounded-sm"
        >
          取消
        </button>
        <button
          @click="handleSubmit"
          class="px-5 py-2 text-xs font-bold text-white bg-[#0f172a] hover:bg-slate-800 rounded-sm"
        >
          创建项目
        </button>
      </div>
    </div>
  </div>
</template>
