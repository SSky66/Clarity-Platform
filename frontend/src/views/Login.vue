<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { login as apiLogin, register as apiRegister } from '@/api/auth'

const router = useRouter()
const auth = useAuthStore()
const toast = useToastStore()

const activeTab = ref('login')

const loginForm = ref({
  role: 'manufacturer',
  account: '',
  password: ''
})

const registerForm = ref({
  role: 'manufacturer',
  company: '',
  account: '',
  password: ''
})

const canvasContainer = ref(null)
let renderer = null
let animationId = null

function switchTab(tab) {
  activeTab.value = tab
}

async function handleLogin() {
  const { account, password, role } = loginForm.value

  if (!account || account.length < 5) {
    toast.error('账号最少5位')
    return
  }
  if (!password || password.length < 8) {
    toast.error('密码最少8位')
    return
  }

  try {
    const res = await apiLogin({ account, password, role: role.toUpperCase() })
    const token = res.access_token
    const user = res.user
    auth.setAuth(token, user)
    toast.success('登录成功！欢迎回来，' + (user.display_name || user.account))
    router.push('/' + user.role.toLowerCase())
  } catch (e) {
    console.error('登录失败', e)
    const detail = e.response?.data?.detail
    const msg = typeof detail === 'string' ? detail : JSON.stringify(detail)
    toast.error('登录失败: ' + (msg || e.message))
  }
}

async function handleRegister() {
  const { role, company, account, password } = registerForm.value

  if (!company || company.length < 3) {
    toast.error('企业名称最少3位')
    return
  }
  if (!account || account.length < 5) {
    toast.error('账号最少5位')
    return
  }
  if (!password || password.length < 6) {
    toast.error('密码最少6位')
    return
  }

  try {
    await apiRegister({
      account,
      password,
      display_name: company,
      role: role.toUpperCase()
    })
    toast.success('注册成功！请使用新账号登录。')
    loginForm.value.account = account
    activeTab.value = 'login'
  } catch (e) {
    console.error('注册失败', e)
    const detail = e.response?.data?.detail
    const msg = typeof detail === 'string' ? detail : JSON.stringify(detail)
    toast.error('注册失败: ' + (msg || e.message))
  }
}

onMounted(() => {
  initThree()
})

onBeforeUnmount(() => {
  if (animationId) {
    cancelAnimationFrame(animationId)
  }
  if (renderer) {
    renderer.dispose()
    const canvas = renderer.domElement
    if (canvas && canvas.parentNode) {
      canvas.parentNode.removeChild(canvas)
    }
  }
})

function initThree() {
  const container = canvasContainer.value
  if (!container) return

  const width = 280
  const height = 280

  const THREE = window.THREE
  if (!THREE) return

  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100)
  camera.position.z = 16
  camera.position.y = 3
  camera.lookAt(0, 0, 0)

  renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true })
  renderer.setSize(width, height)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  container.appendChild(renderer.domElement)

  const SCALE = 2

  // 核心二十面体
  const coreGeometry = new THREE.IcosahedronGeometry(0.6 * SCALE, 1)
  const coreMaterial = new THREE.MeshBasicMaterial({
    color: 0x0ea5e9,
    wireframe: true,
    transparent: true,
    opacity: 0.9
  })
  const core = new THREE.Mesh(coreGeometry, coreMaterial)
  scene.add(core)

  // 创建轨道组
  const orbitGroup = new THREE.Group()
  orbitGroup.rotation.x = Math.PI / 6
  scene.add(orbitGroup)

  // 四个环绕立方体
  const orbitRadius = 2.2 * SCALE
  const cubeSize = 0.8 * SCALE
  const cubes = []
  const industrialBlue = 0x334155

  for (let i = 0; i < 4; i++) {
    const geometry = new THREE.BoxGeometry(cubeSize, cubeSize, cubeSize)
    const material = new THREE.MeshBasicMaterial({
      color: industrialBlue,
      wireframe: true,
      transparent: true,
      opacity: 0.9
    })
    const cube = new THREE.Mesh(geometry, material)
    cube.userData.angle = (i / 4) * Math.PI * 2
    cube.userData.rotationSpeed = {
      x: (Math.random() - 0.5) * 0.02,
      y: (Math.random() - 0.5) * 0.02
    }
    cubes.push(cube)
    orbitGroup.add(cube)
  }

  // 立方体间连接线
  const lineMaterial = new THREE.LineBasicMaterial({
    color: 0x475569,
    transparent: true,
    opacity: 0.4
  })
  const lineGeometry = new THREE.BufferGeometry()
  const linePositions = new Float32Array(4 * 2 * 3)
  lineGeometry.setAttribute('position', new THREE.BufferAttribute(linePositions, 3))
  const lines = new THREE.LineSegments(lineGeometry, lineMaterial)
  orbitGroup.add(lines)

  // 中心到各立方体的连线
  const centerLineMaterial = new THREE.LineBasicMaterial({
    color: 0x0ea5e9,
    transparent: true,
    opacity: 0.2
  })
  const centerLineGeometry = new THREE.BufferGeometry()
  const centerLinePositions = new Float32Array(4 * 2 * 3)
  centerLineGeometry.setAttribute('position', new THREE.BufferAttribute(centerLinePositions, 3))
  const centerLines = new THREE.LineSegments(centerLineGeometry, centerLineMaterial)
  orbitGroup.add(centerLines)

  // 粒子效果
  const particlesGeometry = new THREE.BufferGeometry()
  const particlesCount = 24
  const posArray = new Float32Array(particlesCount * 3)

  for (let i = 0; i < particlesCount * 3; i++) {
    posArray[i] = (Math.random() - 0.5) * 6 * SCALE
  }

  particlesGeometry.setAttribute('position', new THREE.BufferAttribute(posArray, 3))
  const particlesMaterial = new THREE.PointsMaterial({
    size: 0.04 * SCALE,
    color: 0x94a3b8,
    transparent: true,
    opacity: 0.5
  })
  const particlesMesh = new THREE.Points(particlesGeometry, particlesMaterial)
  scene.add(particlesMesh)

  function animate() {
    animationId = requestAnimationFrame(animate)

    const time = Date.now() * 0.001

    // 核心脉动
    core.rotation.y -= 0.02
    core.rotation.x += 0.01
    const pulse = 1 + Math.sin(time * 3) * 0.15
    core.scale.set(pulse, pulse, pulse)

    const orbitSpeed = 0.4
    const positions = []

    cubes.forEach((cube, i) => {
      const angle = cube.userData.angle + time * orbitSpeed
      const x = Math.cos(angle) * orbitRadius
      const z = Math.sin(angle) * orbitRadius
      const y = Math.sin(time * 0.5 + i) * 0.2 * SCALE

      cube.position.set(x, y, z)
      positions.push({ x, y, z })

      cube.rotation.x += cube.userData.rotationSpeed.x
      cube.rotation.y += cube.userData.rotationSpeed.y
    })

    // 更新连线
    for (let i = 0; i < 4; i++) {
      const idx = i * 6
      const curr = positions[i]
      const next = positions[(i + 1) % 4]

      linePositions[idx] = curr.x
      linePositions[idx + 1] = curr.y
      linePositions[idx + 2] = curr.z
      linePositions[idx + 3] = next.x
      linePositions[idx + 4] = next.y
      linePositions[idx + 5] = next.z
    }
    lines.geometry.attributes.position.needsUpdate = true

    for (let i = 0; i < 4; i++) {
      const idx = i * 6
      const pos = positions[i]

      centerLinePositions[idx] = 0
      centerLinePositions[idx + 1] = 0
      centerLinePositions[idx + 2] = 0
      centerLinePositions[idx + 3] = pos.x
      centerLinePositions[idx + 4] = pos.y
      centerLinePositions[idx + 5] = pos.z
    }
    centerLines.geometry.attributes.position.needsUpdate = true

    particlesMesh.rotation.y = time * 0.05

    renderer.render(scene, camera)
  }

  animate()
}
</script>

<template>
  <div class="h-screen w-screen flex items-center justify-center relative overflow-hidden" style="background-color: #0b1120;">
    <!-- 背景层 -->
    <div class="absolute inset-0 z-0 bg-[radial-gradient(rgba(255,255,255,0.15)_1px,transparent_1px)] bg-[length:24px_24px]"></div>
    <div class="absolute top-[-10%] left-[-10%] w-[600px] h-[600px] bg-blue-600/40 rounded-full blur-[140px] z-0"></div>
    <div class="absolute bottom-[-15%] right-[-5%] w-[700px] h-[700px] bg-cyan-500/30 rounded-full blur-[160px] z-0"></div>

    <!-- 核心面板 -->
    <div class="w-full max-w-[880px] flex flex-col md:flex-row relative z-10 mx-4 overflow-hidden"
      style="box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.05); border-radius: 12px; height: 520px; max-height: 90vh;">

      <!-- 左侧：立体图案 -->
      <div class="w-full md:w-[45%] bg-slate-50 border-r border-slate-200 p-10 flex flex-col items-center justify-center relative">
        <div ref="canvasContainer" class="w-[280px] h-[280px] mb-2 relative flex items-center justify-center"></div>

        <div class="text-center mt-2">
          <h1 class="text-2xl font-bold text-slate-900 tracking-wide mb-2">Clarity 澄澈系统</h1>
          <p class="text-xs text-slate-500 leading-relaxed font-medium">
            面向高端制造的工业视觉模型审计协议<br>
            <span class="text-[10px] opacity-70 mt-1 block tracking-widest uppercase font-mono">Zero-Trust Technical Notary</span>
          </p>
        </div>
      </div>

      <!-- 右侧：表单 -->
      <div class="w-full md:w-[55%] bg-white px-12 py-10 flex flex-col justify-center">
        <!-- Tab 切换 -->
        <div class="flex justify-center gap-12 mb-8 text-[15px] font-bold">
          <button
            class="pb-2 border-b-2 tracking-widest outline-none transition-all duration-300"
            :class="activeTab === 'login' ? 'text-[#0f172a] border-[#0f172a]' : 'text-slate-400 border-transparent hover:text-slate-500'"
            @click="switchTab('login')"
          >
            登录
          </button>
          <button
            class="pb-2 border-b-2 tracking-widest outline-none transition-all duration-300"
            :class="activeTab === 'register' ? 'text-[#0f172a] border-[#0f172a]' : 'text-slate-400 border-transparent hover:text-slate-500'"
            @click="switchTab('register')"
          >
            注册
          </button>
        </div>

        <!-- 登录面板 -->
        <div v-show="activeTab === 'login'" class="space-y-5" style="animation: fadeIn 0.3s ease;">
          <form @submit.prevent="handleLogin" class="space-y-5">
            <div class="input-wrapper border border-slate-300 rounded-sm bg-white flex items-stretch overflow-hidden h-11">
              <div class="bg-slate-50 w-20 flex items-center justify-center border-r border-slate-300 shrink-0">
                <span class="text-slate-600 font-bold text-xs tracking-widest">角色</span>
              </div>
              <div class="relative flex-1 bg-white">
                <select v-model="loginForm.role" class="w-full h-full bg-transparent px-4 text-xs text-slate-800 font-bold focus:outline-none cursor-pointer relative z-10 appearance-none">
                  <option value="manufacturer">制造商</option>
                  <option value="supplier">供应商</option>
                  <option value="auditor">审计节点</option>
                  <option value="admin">超级管理员</option>
                </select>
                <div class="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none text-slate-400">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
                </div>
              </div>
            </div>

            <div class="input-wrapper border border-slate-300 rounded-sm bg-white flex items-stretch overflow-hidden h-11">
              <div class="bg-slate-50 w-20 flex items-center justify-center border-r border-slate-300 shrink-0">
                <span class="text-slate-600 font-bold text-xs tracking-widest">账号</span>
              </div>
              <input v-model="loginForm.account" type="text" placeholder="输入企业登录账号或UID" class="flex-1 bg-transparent px-4 text-xs text-slate-800 focus:outline-none placeholder-slate-400 font-bold">
            </div>

            <div class="input-wrapper border border-slate-300 rounded-sm bg-white flex items-stretch overflow-hidden h-11">
              <div class="bg-slate-50 w-20 flex items-center justify-center border-r border-slate-300 shrink-0">
                <span class="text-slate-600 font-bold text-xs tracking-widest">密码</span>
              </div>
              <input v-model="loginForm.password" type="password" placeholder="••••••••" autocomplete="new-password" class="flex-1 bg-transparent px-4 text-sm text-slate-800 focus:outline-none tracking-widest placeholder-slate-400 font-bold">
            </div>

            <div class="flex justify-end pt-1">
              <a href="#" class="text-[11px] font-bold text-slate-400 hover:text-slate-800 transition-colors uppercase tracking-widest">忘记密码?</a>
            </div>

            <div class="pt-3">
              <button type="submit" class="w-full bg-[#0f172a] hover:bg-slate-800 text-white font-bold text-xs h-11 rounded-sm transition-colors shadow-sm tracking-widest flex items-center justify-center gap-2">
                进入系统
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>
              </button>
            </div>
          </form>
        </div>

        <!-- 注册面板 -->
        <div v-show="activeTab === 'register'" class="space-y-4" style="animation: fadeIn 0.3s ease;">
          <form @submit.prevent="handleRegister" class="space-y-4">
            <div class="input-wrapper border border-slate-300 rounded-sm bg-white flex items-stretch overflow-hidden h-11">
              <div class="bg-slate-50 w-20 flex items-center justify-center border-r border-slate-300 shrink-0">
                <span class="text-slate-600 font-bold text-xs tracking-widest">角色</span>
              </div>
              <div class="relative flex-1 bg-white">
                <select v-model="registerForm.role" class="w-full h-full bg-transparent px-4 text-xs text-slate-800 font-bold focus:outline-none cursor-pointer relative z-10 appearance-none">
                  <option value="manufacturer">制造商</option>
                  <option value="supplier">供应商</option>
                  <option value="auditor">审计节点</option>
                </select>
                <div class="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none text-slate-400">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
                </div>
              </div>
            </div>

            <div class="input-wrapper border border-slate-300 rounded-sm bg-white flex items-stretch overflow-hidden h-11">
              <div class="bg-slate-50 w-20 flex items-center justify-center border-r border-slate-300 shrink-0">
                <span class="text-slate-600 font-bold text-xs tracking-widest">企业</span>
              </div>
              <input v-model="registerForm.company" type="text" placeholder="输入企业名称" class="flex-1 bg-transparent px-4 text-xs text-slate-800 focus:outline-none placeholder-slate-400 font-bold">
            </div>

            <div class="input-wrapper border border-slate-300 rounded-sm bg-white flex items-stretch overflow-hidden h-11">
              <div class="bg-slate-50 w-20 flex items-center justify-center border-r border-slate-300 shrink-0">
                <span class="text-slate-600 font-bold text-xs tracking-widest">账号</span>
              </div>
              <input v-model="registerForm.account" type="text" placeholder="设置登录账号" class="flex-1 bg-transparent px-4 text-xs text-slate-800 focus:outline-none placeholder-slate-400 font-bold">
            </div>

            <div class="input-wrapper border border-slate-300 rounded-sm bg-white flex items-stretch overflow-hidden h-11">
              <div class="bg-slate-50 w-20 flex items-center justify-center border-r border-slate-300 shrink-0">
                <span class="text-slate-600 font-bold text-xs tracking-widest">密码</span>
              </div>
              <input v-model="registerForm.password" type="password" placeholder="设置密码（至少8位）" autocomplete="new-password" class="flex-1 bg-transparent px-4 text-xs text-slate-800 focus:outline-none tracking-widest placeholder-slate-400 font-bold">
            </div>

            <div class="pt-1">
              <p class="text-[11px] text-slate-400 leading-relaxed">
                <span class="text-blue-500 font-bold">提示：</span>注册成功后，系统将自动为您生成FISCO BCOS链上钱包地址。
              </p>
            </div>

            <div class="pt-2">
              <button type="submit" class="w-full bg-[#0f172a] hover:bg-slate-800 text-white font-bold text-xs h-11 rounded-sm transition-colors shadow-sm tracking-widest flex items-center justify-center gap-2">
                创建账户
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- 底部 -->
    <div class="absolute bottom-6 text-center w-full z-0">
      <p class="text-[10px] text-slate-500 font-mono tracking-widest opacity-80 flex items-center justify-center gap-2">
        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"></path></svg>
        POWERED BY FISCO BCOS
      </p>
    </div>
  </div>
</template>

<style scoped>
.input-wrapper {
  transition: all 0.2s ease;
}
.input-wrapper:focus-within {
  border-color: #0f172a;
  box-shadow: 0 0 0 1px #0f172a;
}

select {
  -webkit-appearance: none;
  -moz-appearance: none;
  appearance: none;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
