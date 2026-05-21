import request from './request'

export const register = (data) => request.post('/auth/register', data)
export const login = (data) => request.post('/auth/login', data)
export const sudo = (targetUserId) => request.post('/auth/sudo', null, { params: { target_user_id: targetUserId } })
export const getMe = () => request.get('/users/me')
export const listUsers = () => request.get('/users')
export const recharge = (amount) => request.post('/users/recharge', null, { params: { amount } })
export const getStakeRatio = (userId) => request.get(`/users/${userId}/stake-ratio`)