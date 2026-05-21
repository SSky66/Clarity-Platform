<script setup>
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

const emit = defineEmits(['close'])
const authStore = useAuthStore()
const userRole = computed(() => authStore.userRole)

const manufacturerSteps = [
  {
    title: '创建验收项目',
    desc: '在项目大厅点击「创建新的验收需求」，填写项目名称、硬性指标（漏杀率/误杀率容忍度）、协商指标（mAP/F1）及模型评估阈值参数。',
    icon: 'M12 6v6m0 0v6m0-6h6m-6 0H6'
  },
  {
    title: '上传测试数据集',
    desc: '供应商接单后项目进入 UPLOADING 状态，点击「点击上传数据」，将带标签测试集、无缺陷对照集及 YAML 配置文件打包为 .zip 上传至 IPFS。',
    icon: 'M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12'
  },
  {
    title: '质押资金',
    desc: '选择担保方式（全额保证金 3x 基础服务费，或购买协会保险仅缴纳基础质押金）。双方均质押完成后项目进入 PREPARED，等待审计节点调度。',
    icon: 'M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z'
  },
  {
    title: '查看审计结果',
    desc: '审计节点完成计算后，系统生成技术报告（含准确度、注意力、置信度三方面指标及 PASS/REJECT/SLASH 判定）。可在项目大厅查看结果与链上存证。',
    icon: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z'
  },
  {
    title: '现场验收签名',
    desc: '供应商赴现场部署模型后，双方共同实测边缘端延迟、漏杀率、误杀率等指标。确认达标后完成双重签名，智能合约自动释放剩余质押金。若拒签可触发整改期。',
    icon: 'M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z'
  }
]

const supplierSteps = [
  {
    title: '接入新项目',
    desc: '在项目大厅点击「接入新的验收需求」，输入制造商提供的项目 ID（Task Hash），系统校验通过后展示验收标准并进入 UPLOADING 状态。',
    icon: 'M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z'
  },
  {
    title: '上传 TorchScript 模型',
    desc: '确认验收标准后，上传经 torch.jit.script 导出的 .pt 模型文件。模型将加密存储至 IPFS，Hash 值写入智能合约存证。',
    icon: 'M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12'
  },
  {
    title: '质押资金',
    desc: '缴纳基础质押金（含审计服务费）。双方均质押完成后项目进入 PREPARED，等待审计节点调度执行三步审计计算。',
    icon: 'M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z'
  },
  {
    title: '等待审计结果',
    desc: '审计节点执行计算期间，项目处于 AUDITING 状态。审计完成后系统生成技术报告（PASS/REJECT/SLASH），可在项目大厅查看结果与链上存证。',
    icon: 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z'
  },
  {
    title: '现场履约确认',
    desc: '线上审计通过后，赴制造商现场部署模型。双方实测指标达标后完成双重签名，若制造商拒签可进入 168 小时整改期（最多 2 次，每次需追加质押）。',
    icon: 'M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z'
  }
]

const auditorSteps = [
  {
    title: '保持节点在线',
    desc: '本地运行 audit_worker.py 脚本，每 10 秒向服务器发送心跳包。前端显示节点状态为「在线」时，方可接收 AUDITING 任务。超过 30 秒无心跳则显示「已下线」。',
    icon: 'M5.636 18.364a9 9 0 010-12.728m12.728 0a9 9 0 010 12.728m-9.9-2.829a5 5 0 010-7.07m7.072 0a5 5 0 010 7.07M13 12a1 1 0 11-2 0 1 1 0 012 0z'
  },
  {
    title: '调度计算任务',
    desc: '在任务队列中查看 PREPARED 状态的就绪工单，点击「调度计算节点」将项目状态变为 AUDITING。服务器随后将 task_id 和 IPFS 下载链接返回给 audit_worker.py。',
    icon: 'M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z M21 12a9 9 0 11-18 0 9 9 0 0118 0z'
  },
  {
    title: '执行三步审计',
    desc: 'audit_worker.py 自动调用 check.py 执行：①准确度审计（FNR/FPR）②注意力审计（D-RISE 热力图 + Concentration Ratio）③置信度审计（Avg FP / Arrogance）。',
    icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01'
  },
  {
    title: '查看监控大屏',
    desc: '审计执行期间，点击「查看监控大屏」进入实时监控页面，可观察终端日志输出、D-RISE 注意力热力图、置信度分析等审计过程可视化数据。',
    icon: 'M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z'
  },
  {
    title: '提交审计报告',
    desc: '审计完成后，脚本将包含误杀率、漏杀率等判定结果的 JSON 及技术报告 PDF POST 提交给服务器。系统自动扣除服务费并更新状态机，随后脚本恢复轮询。',
    icon: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z'
  }
]

const currentSteps = computed(() => {
  switch (userRole.value) {
    case 'MANUFACTURER': return manufacturerSteps
    case 'SUPPLIER': return supplierSteps
    case 'AUDITOR': return auditorSteps
    default: return manufacturerSteps
  }
})

const roleTitle = computed(() => {
  switch (userRole.value) {
    case 'MANUFACTURER': return '制造商'
    case 'SUPPLIER': return '供应商'
    case 'AUDITOR': return '审计节点'
    default: return '用户'
  }
})
</script>

<template>
  <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-sm shadow-xl w-full max-w-2xl overflow-hidden flex flex-col border border-slate-300 max-h-[90vh]">
      <!-- 头部 -->
      <div class="px-6 py-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center shrink-0">
        <div>
          <h2 class="text-sm font-bold text-slate-800">新手指引</h2>
          <p class="text-xs text-slate-500 mt-1">{{ roleTitle }}操作流程</p>
        </div>
        <button @click="emit('close')" class="text-slate-400 hover:text-slate-700">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>

      <!-- 内容 -->
      <div class="p-6 overflow-y-auto flex-1">
        <div class="relative">
          <!-- 时间线竖线 -->
          <div class="absolute left-[19px] top-8 bottom-4 w-px bg-slate-200"></div>

          <div class="space-y-6">
            <div
              v-for="(step, idx) in currentSteps"
              :key="idx"
              class="relative flex items-start gap-4"
            >
              <!-- 步骤序号圆圈 -->
              <div class="relative z-10 w-10 h-10 rounded-full bg-[#0f172a] flex items-center justify-center text-white shrink-0 shadow-sm">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" :d="step.icon"></path>
                </svg>
              </div>

              <!-- 步骤内容 -->
              <div class="flex-1 pt-1">
                <div class="flex items-center gap-2 mb-1">
                  <span class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">步骤 {{ idx + 1 }}</span>
                </div>
                <h3 class="text-sm font-bold text-slate-800 mb-1.5">{{ step.title }}</h3>
                <p class="text-xs text-slate-600 leading-relaxed">{{ step.desc }}</p>
              </div>
            </div>
          </div>
        </div>

        <!-- 底部提示 -->
        <div class="mt-6 pt-4 border-t border-slate-200">
          <div class="bg-slate-50 border border-slate-200 rounded-sm p-3 flex items-start gap-2">
            <svg class="w-4 h-4 text-slate-500 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>
            <p class="text-xs text-slate-600 leading-relaxed">
              如需查看详细的审计算法原理、智能合约规则或术语解释，请联系系统管理员获取完整技术文档。
            </p>
          </div>
        </div>
      </div>

      <!-- 底部 -->
      <div class="px-6 py-4 border-t border-slate-200 bg-slate-50 flex justify-end shrink-0">
        <button
          @click="emit('close')"
          class="px-5 py-2 text-xs font-bold text-white bg-[#0f172a] hover:bg-slate-800 rounded-sm transition-colors"
        >
          知道了
        </button>
      </div>
    </div>
  </div>
</template>
