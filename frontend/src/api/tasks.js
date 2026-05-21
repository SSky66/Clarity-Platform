import request from './request'

// 项目基础操作
export const createTask = (data) => request.post('/tasks', data)
export const listTasks = (params) => request.get('/tasks', { params })
export const getTask = (id) => request.get(`/tasks/${id}`)
export const getTaskStats = () => request.get('/tasks/stats')

// 供应商接单
export const acceptTask = (id) => request.put(`/tasks/${id}/accept`)
export const acceptTaskByHash = (hash) => request.put(`/tasks/accept-by-hash`, null, { params: { task_hash: hash } })

// 文件上传
export const uploadDataset = (id, file) => {
  const form = new FormData()
  form.append('file', file)
  return request.post(`/tasks/${id}/upload-dataset`, form, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}
export const uploadModel = (id, file) => {
  const form = new FormData()
  form.append('file', file)
  return request.post(`/tasks/${id}/upload-model`, form, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// 阶段2: 准备与质押
export const manufacturerPrepare = (id, data) => request.post(`/tasks/${id}/manufacturer-prepare`, data)
export const supplierPrepare = (id, data) => request.post(`/tasks/${id}/supplier-prepare`, data)
export const withdrawIfTimeout = (id) => request.post(`/tasks/${id}/withdraw-if-timeout`)
// 兼容旧命名
export const stakeFunds = manufacturerPrepare

// 阶段3: 审计
export const startAudit = (id) => request.put(`/tasks/${id}/start-audit`)
export const submitReport = (id, data) => request.post(`/tasks/${id}/report`, data)

// 阶段4: 线上申诉后处理
export const completeReject = (id) => request.post(`/tasks/${id}/complete-reject`)
export const completeSlash = (id) => request.post(`/tasks/${id}/complete-slash`)

// 阶段5: 现场验收
export const submitCompletion = (id) => request.post(`/tasks/${id}/submit-completion`)
export const confirmOnsite = (id, data) => request.post(`/tasks/${id}/confirm-onsite`, data)
export const timeoutAutoPass = (id) => request.post(`/tasks/${id}/timeout-auto-pass`)
// 兼容旧命名
export const fieldSign = confirmOnsite

// 阶段6: 整改
export const requestExtension = (id) => request.post(`/tasks/${id}/request-extension`)
export const submitRectification = (id) => request.post(`/tasks/${id}/submit-rectification`)
export const escalateFieldDispute = (id, data) => request.post(`/tasks/${id}/escalate-field-dispute`, data)

// 阶段3.5: PASS后进入现场验收
export const advanceToAcceptance = (id) => request.post(`/tasks/${id}/advance-to-acceptance`)

// 阶段4: 申诉
export const startAppeal = (id) => request.post(`/tasks/${id}/start-appeal`)
export const initiateFieldAppeal = (id, data) => request.post(`/tasks/${id}/initiate-field-appeal`, data)

// 报告与日志
export const getReport = (id) => request.get(`/tasks/${id}/report`)
export const getAuditLogs = (id) => request.get(`/tasks/${id}/audit-logs`)

// 存证查询
export const getEvidenceData = (id) => request.get(`/tasks/${id}/evidence/data`)
export const getEvidenceModel = (id) => request.get(`/tasks/${id}/evidence/model`)
export const getEvidenceAudit = (id) => request.get(`/tasks/${id}/evidence/audit`)
export const getEvidenceOnsite = (id) => request.get(`/tasks/${id}/evidence/onsite`)
export const getEvidenceAppeal = (id) => request.get(`/tasks/${id}/evidence/appeal`)
export const isEvidenceComplete = (id) => request.get(`/tasks/${id}/evidence/complete`)

// 申诉相关
export const createAppeal = (data) => request.post('/appeals', data)

// 定时任务（ADMIN）
export const processTimeouts = () => request.post('/tasks/process-timeouts')
