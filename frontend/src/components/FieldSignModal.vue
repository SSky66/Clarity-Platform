<script setup>
import { reactive, computed, ref } from 'vue'
import { useToastStore } from '@/stores/toast'
import { useAuthStore } from '@/stores/auth'
import { confirmOnsite, submitCompletion } from '@/api/tasks'

const props = defineProps({
  task: { type: Object, required: true }
})

const emit = defineEmits(['close', 'signed'])
const toast = useToastStore()
const authStore = useAuthStore()

// 判断当前角色：制造商/供应商？（从auth store获取当前用户ID）
const currentUserId = computed(() => authStore.user?.id)
const isManufacturer = computed(() => props.task?.manufacturer_id === currentUserId.value)
const isSupplier = computed(() => props.task?.supplier_id === currentUserId.value)

// 判断当前状态
const isAcceptance = computed(() => props.task?.status === 'ACCEPTANCE')
const isRectification = computed(() => props.task?.status === 'RECTIFICATION')

// 判断制造商是否已拒绝（供应商二次确认场景）
const mfrRejected = computed(() => props.task?.mfr_confirmed === true && props.task?.mfr_satisfied === false)

const form = reactive({
  satisfied: true,
  measured_map: 0.87,
  edge_latency_ms: 45,
  field_fpr: 1.2,
  field_fnr: 0.1,
  deviation_note: '',
  evidence_hash: ''
})

// 供应商在制造商拒绝后的二次选择
const showSupplierSecondChoice = ref(false)
const supplierSecondChoice = ref('') // 'rectify' | 'appeal'

async function handleSign() {
  try {
    // 与后端 FieldSignPayload / confirmOnsite 对齐
    const payload = {
      satisfied: form.satisfied,
      measured_map: form.measured_map || null,
      evidence_hash: form.evidence_hash || null,
      field_actual_fnr: form.field_fnr || null,
      field_actual_fpr: form.field_fpr || null,
      field_actual_latency: form.edge_latency_ms || null,
      field_environment_notes: form.deviation_note || null
    }

    await confirmOnsite(props.task.id, payload)

    const roleLabel = isManufacturer.value ? '制造商' : '供应商'
    if (form.satisfied) {
      toast.success(`${roleLabel}验收签名已提交！等待另一方确认以完成共识。`)
    } else {
      if (isSupplier.value && mfrRejected.value) {
        // 供应商在制造商拒绝后的选择：已在前端处理，这里只是确认
        toast.success('供应商回应已提交。')
      } else {
        toast.success(`${roleLabel}已拒绝验收。等待另一方回应（整改或申诉）。`)
      }
    }
    emit('signed')
  } catch (e) {
    console.error('现场验收签名失败', e)
    toast.error('签名失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function handleSubmitCompletion() {
  // 供应商提交"部署完成"，触发72h验收等待期
  try {
    await submitCompletion(props.task.id)
    toast.success('部署完成已提交！制造商有 72 小时进行验收确认。')
    emit('signed')
  } catch (e) {
    console.error('提交完成失败', e)
    toast.error('提交失败: ' + (e.response?.data?.detail || e.message))
  }
}

function handleReject() {
  form.satisfied = false
  handleSign()
}

// 供应商在制造商拒绝后的二次选择
function handleSupplierChoice(choice) {
  supplierSecondChoice.value = choice
  if (choice === 'rectify') {
    // 接受整改：satisfied=true表示接受整改
    form.satisfied = true
    handleSign()
  } else if (choice === 'appeal') {
    // 提起现场申诉：satisfied=false表示不认同，提起申诉
    form.satisfied = false
    handleSign()
  }
}
</script>

<template>
  <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-sm shadow-xl w-full max-w-xl overflow-hidden flex flex-col border border-slate-300">
      <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
        <h2 class="text-sm font-bold text-slate-800">
          {{ isAcceptance && isSupplier ? '提交部署完成' : '现场验收确认' }}
        </h2>
        <button @click="emit('close')" class="text-slate-400 hover:text-slate-700">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>

      <!-- 供应商二次选择：制造商已拒绝，供应商选择整改或申诉（优先级高于提交完成）-->
      <div v-if="isSupplier && mfrRejected && isAcceptance" class="p-6 space-y-5 bg-white">
        <div class="bg-amber-50 border border-amber-200 rounded-sm p-3">
          <div class="text-xs font-bold text-amber-800 mb-1">制造商已拒绝验收</div>
          <div class="text-[10px] text-amber-600">
            项目：{{ task.task_name }} (ID: {{ task.id }})
          </div>
        </div>
        <p class="text-xs text-slate-600">
          制造商对现场验收结果不满意。作为供应商，您需要选择：
        </p>
        <div class="space-y-3">
          <button
            @click="handleSupplierChoice('rectify')"
            class="w-full p-3 border border-emerald-200 bg-emerald-50 rounded-sm text-left hover:bg-emerald-100 transition-colors"
          >
            <div class="text-xs font-bold text-emerald-800">接受整改</div>
            <div class="text-[10px] text-emerald-600 mt-1">进入 7 天整改期，整改完成后重新验收</div>
          </button>
          <button
            @click="handleSupplierChoice('appeal')"
            class="w-full p-3 border border-rose-200 bg-rose-50 rounded-sm text-left hover:bg-rose-100 transition-colors"
          >
            <div class="text-xs font-bold text-rose-800">提起现场申诉</div>
            <div class="text-[10px] text-rose-600 mt-1">不认同制造商拒绝理由，请求协会仲裁员介入裁决</div>
          </button>
        </div>
      </div>

      <!-- 供应商在ACCEPTANCE阶段：提交部署完成 -->
      <div v-else-if="isAcceptance && isSupplier" class="p-6 space-y-5 bg-white">
        <div class="bg-blue-50 border border-blue-200 rounded-sm p-3">
          <div class="text-xs font-bold text-blue-800 mb-1">提交现场部署完成</div>
          <div class="text-[10px] text-blue-600">
            项目：{{ task.task_name }} (ID: {{ task.id }})
          </div>
        </div>
        <p class="text-xs text-slate-600">
          提交后，制造商将进入 72 小时验收期。若制造商未响应，系统将自动通过。
        </p>
      </div>

      <!-- 验收确认表单 -->
      <div v-else class="p-6 space-y-5 bg-white">
        <div class="bg-blue-50 border border-blue-200 rounded-sm p-3">
          <div class="text-xs font-bold text-blue-800 mb-1">
            {{ isManufacturer ? '制造商' : '供应商' }}现场验收确认
          </div>
          <div class="text-[10px] text-blue-600">
            项目：{{ task.task_name }} (ID: {{ task.id }})
          </div>
        </div>

        <!-- 是否满意 -->
        <div class="space-y-2">
          <label class="block text-xs font-bold text-slate-700">验收结论</label>
          <div class="flex gap-4">
            <label class="flex items-center gap-2 cursor-pointer">
              <input v-model="form.satisfied" type="radio" :value="true" class="accent-[#0f172a]" />
              <span class="text-xs text-slate-700">满意，通过验收</span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer">
              <input v-model="form.satisfied" type="radio" :value="false" class="accent-rose-600" />
              <span class="text-xs text-slate-700">不满意，拒绝验收</span>
            </label>
          </div>
        </div>

        <div class="space-y-3">
          <label class="block text-xs font-bold text-slate-700">现场实测指标</label>
          <div class="grid grid-cols-2 gap-4">
            <div class="border border-slate-200 rounded-sm p-3 bg-slate-50">
              <div class="text-[10px] font-bold text-slate-500 mb-2 uppercase tracking-wider">线上预验收指标</div>
              <div class="space-y-2">
                <div class="flex justify-between text-xs items-center">
                  <span class="text-slate-500">审计漏杀率(FNR):</span>
                  <span class="font-bold text-slate-800 font-mono">{{ (task.final_fnr * 100)?.toFixed(1) || '0.2' }}%</span>
                </div>
                <div class="flex justify-between text-xs items-center">
                  <span class="text-slate-500">审计误杀率(FPR):</span>
                  <span class="font-bold text-slate-800 font-mono">{{ (task.final_fpr * 100)?.toFixed(1) || '3.4' }}%</span>
                </div>
                <div class="flex justify-between text-xs items-center pt-1 border-t border-slate-200">
                  <span class="text-slate-400">参考 mAP/F1:</span>
                  <span class="font-bold text-slate-600 font-mono">{{ (task.final_map * 100)?.toFixed(1) || '87.3' }}% / {{ task.final_f1 || '0.84' }}</span>
                </div>
              </div>
            </div>

            <div class="border border-blue-200 rounded-sm p-3 bg-white">
              <div class="text-[10px] font-bold text-blue-600 mb-2 uppercase tracking-wider">物理现场实测</div>
              <div class="space-y-1.5">
                <div class="flex items-center justify-between text-xs">
                  <span class="text-slate-600">现场实测mAP:</span>
                  <div class="flex items-end w-16">
                    <input
                      v-model.number="form.measured_map"
                      type="number"
                      step="0.01"
                      class="w-full text-right font-bold text-blue-600 border-b border-slate-300 focus:border-blue-500 outline-none pb-0.5 text-xs"
                    />
                  </div>
                </div>
                <div class="flex items-center justify-between text-xs">
                  <span class="text-slate-600">边缘端延迟(ms):</span>
                  <div class="flex items-end w-14">
                    <input
                      v-model.number="form.edge_latency_ms"
                      type="number"
                      class="w-full text-right font-bold text-blue-600 border-b border-slate-300 focus:border-blue-500 outline-none pb-0.5 text-xs"
                    />
                  </div>
                </div>
                <div class="flex items-center justify-between text-xs">
                  <span class="text-slate-600">实测误杀率(%):</span>
                  <div class="flex items-end w-14">
                    <input
                      v-model.number="form.field_fpr"
                      type="number"
                      step="0.1"
                      class="w-full text-right font-bold text-blue-600 border-b border-slate-300 focus:border-blue-500 outline-none pb-0.5 text-xs"
                    />
                  </div>
                </div>
                <div class="flex items-center justify-between text-xs">
                  <span class="text-slate-600">实测漏杀率(%):</span>
                  <div class="flex items-end w-14">
                    <input
                      v-model.number="form.field_fnr"
                      type="number"
                      step="0.1"
                      class="w-full text-right font-bold text-blue-600 border-b border-slate-300 focus:border-blue-500 outline-none pb-0.5 text-xs"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="space-y-2 pt-2 border-t border-slate-100">
          <label class="block text-xs font-bold text-slate-700">现场环境说明（可选）</label>
          <textarea
            v-model="form.deviation_note"
            placeholder="如现场光照、机床抖动与测试集存在偏差导致精度下降，请在此处注明..."
            class="w-full h-16 border border-slate-300 rounded-sm px-3 py-2 text-xs focus:outline-none focus:border-slate-800 placeholder-slate-400 resize-none"
          ></textarea>
        </div>

        <div class="space-y-2">
          <label class="block text-xs font-bold text-slate-700">测试证据 Hash（可选）</label>
          <input
            v-model="form.evidence_hash"
            type="text"
            placeholder="ipfs://... 或文件哈希"
            class="w-full border border-slate-300 rounded-sm px-3 py-1.5 text-xs focus:outline-none focus:border-slate-800 placeholder-slate-400 font-mono"
          />
        </div>
      </div>

      <div class="px-6 py-4 border-t border-slate-200 bg-slate-50 flex justify-between items-center">
        <!-- 供应商在制造商拒绝后的二次选择：无底部按钮，选择由卡片点击完成 -->
        <template v-if="isSupplier && mfrRejected && isAcceptance">
          <div></div>
          <button
            @click="emit('close')"
            class="px-4 py-2 text-xs font-bold text-slate-600 hover:text-slate-900 bg-white border border-slate-300 rounded-sm"
          >
            关闭
          </button>
        </template>

        <!-- 供应商提交完成 -->
        <template v-else-if="isAcceptance && isSupplier">
          <button
            @click="emit('close')"
            class="px-4 py-2 text-xs font-bold text-slate-600 hover:text-slate-900 bg-white border border-slate-300 rounded-sm"
          >
            取消
          </button>
          <button
            @click="handleSubmitCompletion"
            class="px-4 py-2 text-xs font-bold text-white bg-[#0f172a] hover:bg-slate-800 rounded-sm"
          >
            提交部署完成
          </button>
        </template>

        <!-- 验收确认 -->
        <template v-else>
          <button
            v-if="isManufacturer"
            @click="handleReject"
            class="text-xs font-bold text-slate-600 hover:text-rose-600 underline transition-colors"
          >
            拒签并要求整改
          </button>
          <div v-else></div>
          <div class="flex gap-3">
            <button
              @click="emit('close')"
              class="px-4 py-2 text-xs font-bold text-slate-600 hover:text-slate-900 bg-white border border-slate-300 rounded-sm"
            >
              取消
            </button>
            <button
              @click="handleSign"
              class="px-4 py-2 text-xs font-bold text-white rounded-sm"
              :class="form.satisfied ? 'bg-[#0f172a] hover:bg-slate-800' : 'bg-rose-600 hover:bg-rose-700'"
            >
              {{ form.satisfied ? '确认验收通过' : '确认拒绝验收' }}
            </button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
