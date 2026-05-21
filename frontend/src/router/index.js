import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import Login from '@/views/Login.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/login' },
    { path: '/login', name: 'Login', component: Login },
    {
      path: '/manufacturer',
      name: 'Manufacturer',
      component: () => import('@/views/ManufacturerDashboard.vue'),
      meta: { role: 'MANUFACTURER' }
    },
    {
      path: '/supplier',
      name: 'Supplier',
      component: () => import('@/views/SupplierDashboard.vue'),
      meta: { role: 'SUPPLIER' }
    },
    {
      path: '/auditor',
      name: 'Auditor',
      component: () => import('@/views/AuditorDashboard.vue'),
      meta: { role: 'AUDITOR' }
    },
    {
      path: '/monitor/:taskId',
      name: 'Monitor',
      component: () => import('@/views/AuditMonitorScreen.vue'),
      meta: { role: 'AUDITOR' }
    },
    {
      path: '/blockchain',
      name: 'Blockchain',
      component: () => import('@/views/BlockchainDashboard.vue')
    },
    {
      path: '/admin',
      name: 'Admin',
      component: () => import('@/views/AdminDashboard.vue'),
      meta: { role: 'ADMIN' }
    },
  ]
})

router.beforeEach((to, from, next) => {
  const auth = useAuthStore()
  // 未登录且非登录页 → 踢到登录
  if (to.path !== '/login' && !auth.token) {
    next('/login')
    return
  }
  // 角色不匹配且不是ADMIN → 踢到登录
  if (to.meta.role && to.meta.role !== auth.userRole && auth.userRole !== 'ADMIN') {
    next('/login')
    return
  }
  next()
})

export default router
