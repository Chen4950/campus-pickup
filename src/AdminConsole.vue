<script setup>
import { computed, onMounted, ref } from 'vue'
import { request } from './pickup'

defineProps({ view: String })
const filters = ref({ username: '', shelf: '', suffix: '', status: '' })
const applied = ref({ ...filters.value })
const results = ref(null)
const layout = ref({ shelves: [], anchors: [] })
const newShelf = ref({ id: '', x: '', y: '', anchor: 'ENT' })
const fileInput = ref(null)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const pages = computed(() => Math.max(1, Math.ceil((results.value?.total ?? 0) / (results.value?.page_size ?? 20))))
const statusLabels = { pending: '待取件', picked_up: '已取件', discarded: '已丢弃' }

async function run(action) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try { await action() }
  catch (failure) { error.value = failure.message }
  finally { busy.value = false }
}

async function getShelves() {
  layout.value = await request('/api/admin/shelves')
}

async function listPage(page = 1, criteria = applied.value) {
  results.value = await request('/api/admin/parcels?' + new URLSearchParams({ ...criteria, page }))
  applied.value = criteria
}

function refresh() {
  return run(() => Promise.all([getShelves(), listPage(results.value?.page)]))
}

function importFile() {
  const file = fileInput.value?.files[0]
  if (!file) return
  return run(async () => {
    if (file.size > 450000) throw new Error('CSV 文件过大，请分批导入。')
    const result = await request('/api/admin/parcels/import', { csv: await file.text() })
    if (fileInput.value) fileInput.value.value = ''
    notice.value = '已导入 ' + result.imported + ' 件包裹。'
    await listPage()
  })
}

function discard(parcel) {
  if (!window.confirm('确认丢弃包裹 ' + parcel.code + '？')) return
  return run(async () => {
    await request('/api/admin/parcels/' + parcel.id, undefined, undefined, 'DELETE')
    notice.value = '包裹已丢弃。'
    await listPage(results.value.page)
  })
}

function addShelf() {
  return run(async () => {
    await request('/api/admin/shelves', { ...newShelf.value, id: newShelf.value.id.trim().toUpperCase() })
    newShelf.value = { id: '', x: '', y: '', anchor: 'ENT' }
    notice.value = '货架已新增。'
    await getShelves()
  })
}

function removeShelf(shelf) {
  if (!window.confirm('确认删除货架 ' + shelf.id + '？')) return
  return run(async () => {
    await request('/api/admin/shelves/' + encodeURIComponent(shelf.id), undefined, undefined, 'DELETE')
    notice.value = '货架已删除。'
    await getShelves()
  })
}

onMounted(refresh)
</script>

<template>
  <main class="shell admin-shell">
    <section class="page-heading">
      <h1>{{ view === 'parcels' ? '包裹管理' : '货架管理' }}</h1>
      <button type="button" class="button secondary" :disabled="busy" @click="refresh">刷新</button>
    </section>
    <p v-if="error" class="notice warning" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <template v-if="view === 'parcels'">
      <section class="panel">
        <h2>导入包裹</h2>
        <form class="admin-form" @submit.prevent="importFile">
          <label class="upload-label">UTF-8 CSV 文件<input ref="fileInput" type="file" accept=".csv,text/csv" required></label>
          <button class="button primary" :disabled="busy">导入包裹</button>
        </form>
        <p class="muted compact">表头为 username,code,shelf,level,suffix。用户名须已注册，包裹码须与面单条码或二维码内容一致。</p>
      </section>
      <section class="panel">
        <h2>查询包裹</h2>
        <form class="admin-form filters" @submit.prevent="run(() => listPage(1, { ...filters }))">
          <label>用户名<input v-model.trim="filters.username" maxlength="32" placeholder="输入用户名"></label>
          <label>货架<select v-model="filters.shelf"><option value="">全部货架</option><option v-for="node in layout.anchors.filter(node => node.type !== 'entrance')" :key="node.id">{{ node.id }}</option></select></label>
          <label>面单尾号<input v-model.trim="filters.suffix" maxlength="4" inputmode="numeric" placeholder="输入尾号"></label>
          <label>状态<select v-model="filters.status"><option value="">全部状态</option><option v-for="(label, id) in statusLabels" :key="id" :value="id">{{ label }}</option></select></label>
          <button class="button primary" :disabled="busy">查询</button>
        </form>
        <div v-if="results?.items.length" class="table-wrap" tabindex="0" aria-label="包裹查询结果">
          <table>
            <thead><tr><th>包裹码</th><th>用户名</th><th>货架</th><th>层</th><th>尾号</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="parcel in results.items" :key="parcel.id">
                <td>{{ parcel.code }}</td><td>{{ parcel.username }}</td><td>{{ parcel.shelf }}</td><td>{{ parcel.level }}</td><td>{{ parcel.suffix }}</td><td>{{ statusLabels[parcel.status] }}</td>
                <td><button v-if="parcel.status === 'pending'" type="button" class="button small danger" :disabled="busy" @click="discard(parcel)">丢弃包裹</button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else-if="results" class="notice">没有符合条件的包裹。</p>
        <nav v-if="results?.total" class="pagination" aria-label="分页">
          <span>第 {{ results.page }} / {{ pages }} 页 · 共 {{ results.total }} 件</span>
          <button class="button secondary small" type="button" :disabled="busy || results.page === 1" @click="run(() => listPage(results.page - 1))">上一页</button>
          <button class="button secondary small" type="button" :disabled="busy || results.page >= pages" @click="run(() => listPage(results.page + 1))">下一页</button>
        </nav>
      </section>
    </template>
    <template v-else>
      <section class="panel">
        <h2>新增货架</h2>
        <form class="admin-form filters" @submit.prevent="addShelf">
          <label>编号<input v-model="newShelf.id" placeholder="例如 D1" maxlength="4" required></label>
          <label>X 坐标（米）<input v-model.number="newShelf.x" type="number" min="-1000" max="1000" step="any" required></label>
          <label>Y 坐标（米）<input v-model.number="newShelf.y" type="number" min="-1000" max="1000" step="any" required></label>
          <label>连接点<select v-model="newShelf.anchor" required><option v-for="node in layout.anchors" :key="node.id" :value="node.id">{{ node.id }}（{{ node.x }}, {{ node.y }}）</option></select></label>
          <button class="button primary" :disabled="busy">新增货架</button>
        </form>
      </section>
      <section class="panel">
        <h2>货架列表</h2>
        <div v-if="layout.shelves.length" class="table-wrap" tabindex="0" aria-label="货架列表">
          <table>
            <thead><tr><th>编号</th><th>X 坐标（米）</th><th>Y 坐标（米）</th><th>操作</th></tr></thead>
            <tbody><tr v-for="shelf in layout.shelves" :key="shelf.id">
              <td>{{ shelf.id }}</td><td>{{ shelf.x }}</td><td>{{ shelf.y }}</td>
              <td><button type="button" class="button small danger" :disabled="busy" @click="removeShelf(shelf)">删除货架</button></td>
            </tr></tbody>
          </table>
        </div>
        <p v-else class="notice">暂无货架。</p>
      </section>
    </template>
  </main>
</template>
