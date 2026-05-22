import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('clarity_token') || '')
  const user = ref(JSON.parse(localStorage.getItem('clarity_user') || 'null'))
  // ADMIN 登录时保存，用于后续切换账号
  const adminToken = ref(localStorage.getItem('clarity_admin_token') || '')

  const isLoggedIn = computed(() => !!token.value)
  const userRole = computed(() => user.value?.role || '')
  const isAdmin = computed(() => userRole.value === 'ADMIN')

  function setAuth(t, u) {
    token.value = t
    user.value = u
    localStorage.setItem('clarity_token', t)
    localStorage.setItem('clarity_user', JSON.stringify(u))
    axios.defaults.headers.common['Authorization'] = `Bearer ${t}`
    
    // 如果是 ADMIN 登录，保存 admin_token
    if (u?.role === 'ADMIN') {
      adminToken.value = t
      localStorage.setItem('clarity_admin_token', t)
    }
  }

  function setToken(t) {
    token.value = t
    localStorage.setItem('clarity_token', t)
    axios.defaults.headers.common['Authorization'] = `Bearer ${t}`
  }

  function updateUser(u) {
    user.value = u
    localStorage.setItem('clarity_user', JSON.stringify(u))
  }

  function logout() {
    token.value = ''
    user.value = null
    adminToken.value = ''
    localStorage.removeItem('clarity_token')
    localStorage.removeItem('clarity_user')
    localStorage.removeItem('clarity_admin_token')
    delete axios.defaults.headers.common['Authorization']
  }

  // 页面刷新后恢复
  if (token.value) {
    axios.defaults.headers.common['Authorization'] = `Bearer ${token.value}`
  }

  return { token, user, adminToken, isLoggedIn, userRole, isAdmin, setAuth, setToken, updateUser, logout }
})
