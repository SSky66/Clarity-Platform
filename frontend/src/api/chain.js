import request from './request'

// 旧接口，兼容已有调用
export const listChainEvents = (params) => request.get('/chain-events', { params })

// 新接口
export const getChainHealth = () => request.get('/chain/health')
export const getChainStats = () => request.get('/chain/stats')
export const listChainEventsV2 = (params) => request.get('/chain/events', { params })
export const getChainEventDetail = (txHash) => request.get(`/chain/events/${txHash}`)
