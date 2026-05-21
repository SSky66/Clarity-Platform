import request from './request'

export const listAppeals = () => request.get('/appeals')
export const createAppeal = (data) => request.post('/appeals', data)
export const listPendingAppeals = () => request.get('/appeals/pending')
export const assignArbitrator = (id, data) => request.post(`/appeals/${id}/assign-arbitrator`, data)
export const resolveAppeal = (id, data) => request.post(`/appeals/${id}/resolve`, data)
