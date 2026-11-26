<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { request } from './pickup'
import PickupViews from './PickupViews.vue'
import AdminConsole from './AdminConsole.vue'
import ParcelScanner from './ParcelScanner.vue'

const user = ref(null)
const loading = ref(true)
const registering = ref(false)
const changing = ref(false)
const view = ref('route')
const credentials = ref({ username: '', password: '' })
const passwords = ref({ current_password: '', new_password: '' })
const passwordInput = ref(null)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const isAdmin = computed(() => user.value?.role === 'admin')
const tabs = computed(() => isAdmin.value
  ? [['parcels', '包裹管理'], ['shelves', '货架管理'], ['scan', '扫码取件']]
  : [['route', '取件路线'], ['forecast', '错峰计划']])

function setUser(account) {
  user.value = account
  const mobile = window.matchMedia('(max-width: 740px), (pointer: coarse)').matches
  view.value = account?.role === 'admin' ? (mobile ? 'scan' : 'parcels') : 'route'
  changing.value = false
  registering.value = false
  credentials.value = { username: '', password: '' }
  passwords.value = { current_password: '', new_password: '' }
}

function expired() {
  setUser(null)
  notice.value = ''
  error.value = '登录已失效，请重新登录。'
}

onMounted(async () => {
  window.addEventListener('pickup-session-expired', expired)
  try { setUser(await request('/api/auth/me')) }
  catch (failure) { if (failure.status !== 401) error.value = failure.message }
  finally { loading.value = false }
})
onUnmounted(() => window.removeEventListener('pickup-session-expired', expired))

async function run(action) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try { await action() }
  catch (failure) { error.value = failure.message }
  finally { busy.value = false }
}

function authenticate() {
  return run(async () => {
    const action = registering.value ? 'register' : 'login'
    setUser(await request('/api/auth/' + action, credentials.value))
  })
}

function logout() {
  return run(async () => {
    await request('/api/auth/logout', {})
    setUser(null)
  })
}

async function togglePassword() {
  passwords.value = { current_password: '', new_password: '' }
  error.value = ''
  notice.value = ''
  changing.value = !changing.value
  if (changing.value) {
    await nextTick()
    passwordInput.value?.focus()
  }
}

function changePassword() {
  return run(async () => {
    await request('/api/auth/password', passwords.value)
    await togglePassword()
    notice.value = '密码已修改。'
  })
}
</script>

<template>
  <header class="site-header">
    <div class="header-content account-header">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>
        <span>校园驿站<span class="brand-secondary">取件助手</span></span>
      </div>
      <nav v-if="user" class="navigation" aria-label="主要功能">
        <button v-for="[id, label] in tabs" :key="id" type="button" :aria-current="view === id ? 'page' : null" @click="view = id">{{ label }}</button>
      </nav>
      <nav v-if="user" class="account-actions" aria-label="账号操作">
        <span class="account-name">{{ user.username }}</span>
        <button class="text-button" type="button" :aria-expanded="changing" :disabled="busy" @click="togglePassword">修改密码</button>
        <button class="text-button" type="button" :disabled="busy" @click="logout">退出登录</button>
      </nav>
    </div>
  </header>

  <main v-if="!user" class="shell sign-in">
    <section class="panel">
      <p v-if="loading" role="status">正在检查登录状态…</p>
      <template v-else>
        <h1>{{ registering ? '注册账号' : '登录校园驿站' }}</h1>
        <form class="dialog-form account-form" @submit.prevent="authenticate">
          <label>用户名<input v-model.trim="credentials.username" name="username" autocomplete="username" maxlength="32" required></label>
          <label>密码<input v-model="credentials.password" name="password" type="password" :autocomplete="registering ? 'new-password' : 'current-password'" :minlength="registering ? 8 : 1" maxlength="128" required></label>
          <p v-if="registering" class="muted">用户名可使用文字、数字、下划线、点和连字符。密码至少 8 个字符。</p>
          <button class="button primary full" :disabled="busy">{{ registering ? '注册并登录' : '登录' }}</button>
        </form>
        <p v-if="error" class="notice warning" role="alert">{{ error }}</p>
        <button class="text-button account-switch" type="button" :disabled="busy" @click="registering = !registering; error = ''; credentials.password = ''">
          {{ registering ? '已有账号，返回登录' : '注册新账号' }}
        </button>
      </template>
    </section>
  </main>

  <template v-else>
    <div v-if="changing || error || notice" class="shell account-feedback">
      <section v-if="changing" class="panel password-panel" aria-labelledby="password-heading">
        <h2 id="password-heading">修改密码</h2>
        <form class="dialog-form account-form" @submit.prevent="changePassword">
          <label>当前密码<input ref="passwordInput" v-model="passwords.current_password" type="password" autocomplete="current-password" maxlength="128" required></label>
          <label>新密码<input v-model="passwords.new_password" type="password" autocomplete="new-password" minlength="8" maxlength="128" required></label>
          <div class="heading-actions">
            <button class="button primary" :disabled="busy">保存</button>
            <button class="button secondary" type="button" :disabled="busy" @click="togglePassword">取消</button>
          </div>
        </form>
      </section>
      <p v-if="error" class="notice warning" role="alert">{{ error }}</p>
      <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    </div>
    <PickupViews v-if="!isAdmin" :key="user.username" :view="view" :username="user.username" @navigate="view = $event" />
    <ParcelScanner v-else-if="view === 'scan'" />
    <AdminConsole v-else :view="view" />
  </template>
</template>
