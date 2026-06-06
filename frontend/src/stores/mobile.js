import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useMobileStore = defineStore('mobile', () => {
  // 侧边栏展开状态（移动端默认收起）
  const sidebarOpen = ref(false)

  // 是否移动端（< 768px）
  const isMobile = ref(false)

  // 是否平板（768px - 1024px）
  const isTablet = ref(false)

  function toggleSidebar() {
    sidebarOpen.value = !sidebarOpen.value
  }

  function closeSidebar() {
    sidebarOpen.value = false
  }

  function openSidebar() {
    sidebarOpen.value = true
  }

  // 监听窗口变化
  function updateBreakpoint() {
    const width = window.innerWidth
    isMobile.value = width < 768
    isTablet.value = width >= 768 && width < 1024
    // 切换到桌面端时自动关闭侧边栏
    if (!isMobile.value && !isTablet.value) {
      sidebarOpen.value = false
    }
  }

  return {
    sidebarOpen,
    isMobile,
    isTablet,
    toggleSidebar,
    closeSidebar,
    openSidebar,
    updateBreakpoint,
  }
})
