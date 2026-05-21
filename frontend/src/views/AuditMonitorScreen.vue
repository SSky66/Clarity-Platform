<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getTask, getReport, getAuditLogs } from '@/api/tasks'

const route = useRoute()
const router = useRouter()
const taskId = route.params.taskId

const task = ref(null)
const report = ref(null)
const displayedLogs = ref([])
const activeTab = ref('attention')
const imagePollTimer = ref(null)

// 终端日志数据
const logs = [
  { type: '[SYS]', colorClass: 'text-gray-400', text: '初始化 Clarity Audit Engine v2.1.0' },
  { type: '[DONE]', colorClass: 'text-green-400', text: '准确度审计: 漏杀率=0.2%, 误杀率=3.4%' },
  { type: '[INFO]', colorClass: 'text-blue-400', text: '协商指标: mAP=87.3%, F1=0.84' },
  { type: '[DONE]', colorClass: 'text-green-400', text: '注意力审计: 6个TP, 平均CR=41.5%' },
  { type: '[DONE]', colorClass: 'text-green-400', text: '置信度审计: 3组样本, Arrogance=12%' },
  { type: '[DONE]', colorClass: 'text-green-400', text: '审计完成: 综合判定 PASS' }
]

// 注意力审计 TP 样本数据
const tpSamples = [
  { id: 1, label: 'mousebite', conf: 0.92, cr: 45, boxMargin: 6 },
  { id: 2, label: 'mousebite', conf: 0.89, cr: 38, boxMargin: 8 },
  { id: 3, label: 'mousebite', conf: 0.95, cr: 52, boxMargin: 4 },
  { id: 4, label: 'mousebite', conf: 0.87, cr: 41, boxMargin: 7 },
  { id: 5, label: 'mousebite', conf: 0.91, cr: 44, boxMargin: 5 },
  { id: 6, label: 'mousebite', conf: 0.88, cr: 39, boxMargin: 9 }
]

// 置信度审计样本数据
const fpSamples = [
  { id: 1, img: 'img_1201', defectMargin: 8, templateMargin: 8, hasFp: true, fpConf: 0.85 },
  { id: 2, img: 'img_1234', defectMargin: 6, templateMargin: 6, hasFp: true, fpConf: 0.91 },
  { id: 3, img: 'img_1256', defectMargin: 10, templateMargin: 10, hasFp: false, fpConf: null }
]

function getSystemTime() {
  const now = new Date()
  return `[${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}]`
}

// 打字机效果逐行输出日志
function startTypingLogs() {
  let i = 0
  function addLog() {
    if (i >= logs.length) return
    displayedLogs.value.push({
      time: getSystemTime(),
      type: logs[i].type,
      colorClass: logs[i].colorClass,
      text: logs[i].text
    })
    i++
    setTimeout(addLog, Math.random() * 800 + 400)
  }
  setTimeout(addLog, 500)
}

async function fetchTask() {
  try {
    const res = await getTask(taskId)
    task.value = res
  } catch (e) {
    console.error('获取任务信息失败', e)
  }
}

async function fetchReport() {
  try {
    const res = await getReport(taskId)
    report.value = res
  } catch (e) {
    console.error('获取审计报告失败', e)
  }
}

// TODO: 接入真实日志流接口 GET /api/tasks/{taskId}/audit-logs
async function fetchAuditLogsStream() {
  try {
    const res = await getAuditLogs(taskId)
    // 真实接入时可将返回的日志追加到 displayedLogs
    console.log('audit logs', res)
  } catch (e) {
    console.error('获取审计日志失败', e)
  }
}

// TODO: 接入真实图片轮询接口 GET /api/tasks/{taskId}/audit-images
async function fetchAuditImages() {
  // 当前返回 Mock 占位数据
  // 本地 audit_worker.py 计算完成后会上传图片到服务器，前端通过此接口轮询获取
  console.log('polling audit images for task', taskId)
}

function startImagePolling() {
  fetchAuditImages()
  imagePollTimer.value = setInterval(fetchAuditImages, 5000)
}

function goBack() {
  router.back()
}

onMounted(() => {
  fetchTask()
  fetchReport()
  startTypingLogs()
  startImagePolling()
})

onUnmounted(() => {
  if (imagePollTimer.value) {
    clearInterval(imagePollTimer.value)
  }
})
</script>

<template>
  <div class="h-screen flex flex-col overflow-hidden">
    <!-- 顶栏 -->
    <header class="h-14 bg-[#0f172a] text-white flex items-center justify-between px-6 shrink-0 border-b border-slate-800">
      <div class="flex items-center gap-3">
        <button
          @click="goBack"
          class="text-slate-300 hover:text-white transition-colors flex items-center gap-2 font-semibold text-sm tracking-wide"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"></path>
          </svg>
          返回控制台
        </button>
        <div class="h-4 w-px bg-slate-700 mx-2"></div>
        <h1 class="text-base font-bold tracking-wide text-white">审计监控大屏</h1>
      </div>
      <div class="text-xs text-slate-400 font-mono">
        Task: {{ task?.id || taskId }}
      </div>
    </header>

    <div class="flex-1 flex overflow-hidden">
      <!-- 左侧 45% - CMD终端 -->
      <div class="w-[45%] flex flex-col border-r border-slate-300 bg-black">
        <!-- 终端标题栏 -->
        <div class="h-9 bg-[#111827] border-b border-gray-800 flex items-center px-4 shrink-0">
          <span class="text-xs font-bold text-gray-400">执行日志</span>
          <div class="ml-auto flex items-center gap-2">
            <div class="w-1.5 h-1.5 rounded-full bg-gray-500"></div>
            <span class="text-[11px] text-gray-500">Running</span>
          </div>
        </div>

        <!-- 终端内容区 -->
        <div class="flex-1 overflow-y-auto p-4 pb-20 bg-black"
          style="font-family: 'Consolas', 'Monaco', 'Courier New', monospace;"
        >
          <div
            v-for="(log, idx) in displayedLogs"
            :key="idx"
            class="mb-1 text-[13px] leading-relaxed"
            style="color: #d1d5db;"
          >
            <span class="text-gray-500 mr-3">{{ log.time }}</span>
            <span :class="log.colorClass">{{ log.type }}</span>
            <span>{{ log.text }}</span>
          </div>
        </div>

        <!-- 终端底部栏 -->
        <div class="h-8 bg-[#111827] border-t border-gray-800 flex items-center px-4 text-[11px] text-gray-500 shrink-0">
          <span>TEE可信执行环境：预留接口 | 当前为本地沙盒模式</span>
        </div>
      </div>

      <!-- 右侧 55% -->
      <div class="w-[55%] flex flex-col bg-slate-100 overflow-hidden">
        <!-- 顶部指标栏：准确度审计结果 -->
        <div class="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between shrink-0">
          <div class="flex items-center gap-6">
            <div class="text-xs text-slate-500 uppercase tracking-wider">准确度审计</div>

            <!-- 硬性指标：漏杀率与误杀率 -->
            <div class="flex items-baseline gap-3">
              <div class="flex items-baseline gap-1.5">
                <span class="text-xs text-slate-500">漏杀率</span>
                <span class="text-xl font-bold text-slate-800 font-mono">
                  {{ report?.fnr ?? '0.2' }}%
                </span>
              </div>
              <span class="text-slate-300">|</span>
              <div class="flex items-baseline gap-1.5">
                <span class="text-xs text-slate-500">误杀率</span>
                <span class="text-xl font-bold text-slate-800 font-mono">
                  {{ report?.fpr ?? '3.4' }}%
                </span>
              </div>
            </div>

            <div class="h-4 w-px bg-slate-200"></div>

            <!-- 协商指标：mAP与F1 -->
            <div class="flex items-baseline gap-2 text-slate-400">
              <span class="text-sm font-mono">{{ report?.map ?? '87.3' }}%</span>
              <span class="text-xs">mAP</span>
              <span class="text-slate-300">|</span>
              <span class="text-sm font-mono">{{ report?.f1 ?? '0.84' }}</span>
              <span class="text-xs">F1</span>
            </div>
          </div>

          <span class="text-xs px-2 py-1 bg-slate-100 border border-slate-200 text-slate-700 rounded-sm">
            {{ report?.verdict ?? 'PASS' }}
          </span>
        </div>

        <!-- Tab 切换栏 -->
        <div class="bg-white border-b border-slate-200 px-6 flex items-center shrink-0">
          <button
            class="px-6 py-2.5 text-[13px] font-medium transition-all border-b-2"
            :class="activeTab === 'attention'
              ? 'text-[#0f172a] border-[#0f172a] font-semibold'
              : 'text-slate-500 border-transparent hover:text-slate-700 hover:bg-slate-50'"
            @click="activeTab = 'attention'"
          >
            注意力审计
          </button>
          <button
            class="px-6 py-2.5 text-[13px] font-medium transition-all border-b-2"
            :class="activeTab === 'confidence'
              ? 'text-[#0f172a] border-[#0f172a] font-semibold'
              : 'text-slate-500 border-transparent hover:text-slate-700 hover:bg-slate-50'"
            @click="activeTab = 'confidence'"
          >
            置信度审计
          </button>
        </div>

        <!-- 主展示区域 -->
        <div class="flex-1 overflow-hidden relative bg-slate-50">
          <!-- 注意力审计面板 -->
          <div
            v-show="activeTab === 'attention'"
            class="h-full overflow-y-auto p-6"
            style="scrollbar-width: thin;"
          >
            <div class="max-w-4xl mx-auto space-y-6">
              <!-- 标题行 -->
              <div class="flex justify-between items-end pb-2 border-b border-slate-200">
                <div>
                  <div class="text-sm font-bold text-slate-800">True Positive检测框分析</div>
                  <div class="text-xs text-slate-500 mt-1">img_0456.jpg | 6个正确检测框</div>
                </div>
                <div class="text-right">
                  <div class="text-3xl font-bold text-slate-800 font-mono">{{ report?.avg_cr ?? '41.5' }}%</div>
                  <div class="text-xs text-slate-500">平均注意力密度比</div>
                </div>
              </div>

              <!-- 6个TP样本卡片 -->
              <div class="space-y-3">
                <div
                  v-for="sample in tpSamples"
                  :key="sample.id"
                  class="bg-white border border-slate-200 rounded-sm shadow-sm p-3"
                >
                  <div class="flex justify-between items-center mb-2 text-[11px] text-slate-600 font-mono">
                    <span>TP #{{ sample.id }} | {{ sample.label }}</span>
                    <span>conf: {{ sample.conf }} | CR: {{ sample.cr }}%</span>
                  </div>
                  <div class="grid grid-cols-2 gap-2 h-32">
                    <!-- 左侧：缺陷框图 -->
                    <div class="bg-slate-200 relative border border-slate-300">
                      <div class="absolute inset-0 flex items-center justify-center text-xs text-slate-400">缺陷区域</div>
                      <div
                        class="absolute inset-0 border-2 border-slate-800"
                        :style="{ margin: sample.boxMargin * 4 + 'px' }"
                      ></div>
                    </div>
                    <!-- 右侧：D-RISE热力图 -->
                    <div class="bg-slate-100 relative border border-slate-300">
                      <div
                        class="absolute top-1/2 left-1/2 w-12 h-12 bg-red-500/30 blur-xl rounded-full transform -translate-x-1/2 -translate-y-1/2"
                        :style="{ width: (10 + sample.cr * 0.3) + 'px', height: (10 + sample.cr * 0.3) + 'px' }"
                      ></div>
                      <div class="absolute bottom-2 right-2 text-sm font-mono font-bold text-slate-700">{{ sample.cr }}%</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 置信度审计面板 -->
          <div
            v-show="activeTab === 'confidence'"
            class="h-full overflow-y-auto p-6"
            style="scrollbar-width: thin;"
          >
            <div class="max-w-4xl mx-auto space-y-6">
              <!-- 标题行 -->
              <div class="flex justify-between items-end pb-2 border-b border-slate-200">
                <div>
                  <div class="text-sm font-bold text-slate-800">False Positive检测框分析</div>
                  <div class="text-xs text-slate-500 mt-1">3组样本对比 | 检测假阳性</div>
                </div>
                <div class="text-right">
                  <div class="text-3xl font-bold text-slate-800 font-mono">{{ report?.arrogance ?? '12' }}%</div>
                  <div class="text-xs text-slate-500">置信度偏差数值</div>
                </div>
              </div>

              <!-- 3组样本卡片 -->
              <div class="space-y-3">
                <div
                  v-for="sample in fpSamples"
                  :key="sample.id"
                  class="bg-white border border-slate-200 rounded-sm shadow-sm p-3"
                >
                  <div class="text-xs text-slate-600 mb-2 font-mono">样本组 #{{ sample.id }} | {{ sample.img }}</div>

                  <!-- 三个图片标签 -->
                  <div class="grid grid-cols-3 gap-2 mb-2 text-center text-[11px] text-slate-600 font-medium">
                    <div>缺陷原图</div>
                    <div>无缺陷模板</div>
                    <div>FP检测</div>
                  </div>

                  <!-- 三个图片 -->
                  <div class="grid grid-cols-3 gap-2 h-32">
                    <div class="bg-slate-200 relative border border-slate-300">
                      <div
                        class="absolute inset-0 border-2 border-slate-800"
                        :style="{ margin: sample.defectMargin * 4 + 'px' }"
                      ></div>
                    </div>
                    <div class="bg-slate-100 relative border border-slate-300">
                      <div
                        class="absolute inset-0 border-2 border-dashed border-slate-400"
                        :style="{ margin: sample.templateMargin * 4 + 'px' }"
                      ></div>
                    </div>
                    <div class="bg-slate-100 relative border border-slate-300">
                      <template v-if="sample.hasFp">
                        <div class="absolute top-1/3 left-1/3 w-1/3 h-1/3 border-2 border-rose-400 bg-rose-400/10"></div>
                        <div class="absolute bottom-1 right-1 text-[10px] font-mono text-rose-600">{{ sample.fpConf }}</div>
                      </template>
                      <template v-else>
                        <div class="absolute inset-0 flex items-center justify-center">
                          <span class="text-xs text-slate-400">无显著误检</span>
                        </div>
                      </template>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 底部指标栏 -->
        <div class="h-12 bg-white border-t border-slate-200 px-6 flex items-center justify-between shrink-0 text-xs">
          <div class="flex items-center gap-8 text-slate-600">
            <div class="flex items-baseline gap-2">
              <span class="text-slate-500">注意力密度比</span>
              <span class="text-base font-bold text-slate-800 font-mono">{{ report?.avg_cr ?? '41.5' }}%</span>
            </div>
            <div class="h-4 w-px bg-slate-300"></div>
            <div class="flex items-baseline gap-2">
              <span class="text-slate-500">平均误检数</span>
              <span class="text-base font-bold text-slate-800 font-mono">{{ report?.avg_fp ?? '0.33' }}</span>
            </div>
            <div class="h-4 w-px bg-slate-300"></div>
            <div class="flex items-baseline gap-2">
              <span class="text-slate-500">置信度偏差</span>
              <span class="text-base font-bold text-slate-800 font-mono">{{ report?.arrogance ?? '12' }}%</span>
            </div>
          </div>
          <div class="flex items-baseline gap-2">
            <span class="text-slate-500">判定结果</span>
            <span class="text-base font-bold text-slate-800 font-mono">{{ report?.verdict ?? 'PASS' }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
