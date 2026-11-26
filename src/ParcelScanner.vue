<script setup>
import { nextTick, onUnmounted, ref } from 'vue'
import { request } from './pickup'

const code = ref('')
const parcel = ref(null)
const video = ref(null)
const scanning = ref(false)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const liveAvailable = Boolean(navigator.mediaDevices?.getUserMedia)
let controls
let cameraRun = 0

function stopCamera() {
  cameraRun++
  controls?.stop()
  controls = undefined
  scanning.value = false
}

onUnmounted(stopCamera)

async function reader() {
  const { BrowserMultiFormatReader } = await import('@zxing/browser')
  return new BrowserMultiFormatReader()
}

async function lookup() {
  if (busy.value || !code.value.trim()) return
  stopCamera()
  busy.value = true
  error.value = ''
  notice.value = ''
  parcel.value = null
  try { parcel.value = await request('/api/admin/pickup/lookup', { code: code.value.trim() }) }
  catch (failure) { error.value = failure.message }
  finally { busy.value = false }
}

async function startCamera() {
  stopCamera()
  const run = cameraRun
  scanning.value = true
  error.value = ''
  notice.value = ''
  parcel.value = null
  await nextTick()
  try {
    const decoder = await reader()
    if (run !== cameraRun) return
    const activeControls = await decoder.decodeFromConstraints(
      { audio: false, video: { facingMode: { ideal: 'environment' } } },
      video.value,
      (result, _, scanControls) => {
        if (run !== cameraRun || !result) return
        scanControls.stop()
        code.value = result.getText()
        lookup()
      },
    )
    if (run === cameraRun) controls = activeControls
    else activeControls.stop()
  } catch {
    if (run !== cameraRun) return
    stopCamera()
    error.value = '无法打开相机。请检查权限，或拍照识别面单。'
  }
}

async function scanPhoto(event) {
  const file = event.target.files[0]
  event.target.value = ''
  if (!file) return
  stopCamera()
  error.value = ''
  notice.value = ''
  parcel.value = null
  busy.value = true
  const url = URL.createObjectURL(file)
  try { code.value = (await (await reader()).decodeFromImageUrl(url)).getText() }
  catch { error.value = '未识别到条码或二维码，请靠近面单重新拍摄。' }
  finally {
    URL.revokeObjectURL(url)
    busy.value = false
  }
  if (!error.value) await lookup()
}

async function finish(discard) {
  if (busy.value || !parcel.value) return
  if (discard && !window.confirm('确认丢弃包裹 ' + parcel.value.code + '？')) return
  busy.value = true
  error.value = ''
  const id = parcel.value.id
  try {
    if (discard) await request('/api/admin/parcels/' + id, undefined, undefined, 'DELETE')
    else await request('/api/admin/pickup/' + id, {})
    notice.value = discard ? '包裹已丢弃。' : '包裹已核验出库。'
    parcel.value = null
    code.value = ''
  } catch (failure) {
    error.value = failure.message
    if ([404, 409].includes(failure.status)) parcel.value = null
  } finally { busy.value = false }
}
</script>

<template>
  <main class="shell scanner-shell">
    <div class="page-heading"><h1>扫码取件</h1></div>
    <section class="panel">
      <div class="heading-actions">
        <button v-if="scanning" class="button secondary" type="button" @click="stopCamera">关闭相机</button>
        <button v-else-if="liveAvailable" class="button primary" type="button" :disabled="busy" @click="startCamera">打开相机扫码</button>
      </div>
      <video v-if="scanning" ref="video" class="scan-preview" muted autoplay playsinline></video>
      <p v-if="!liveAvailable" class="muted compact">实时扫码需要 HTTPS。也可拍照识别或手动输入。</p>
      <div class="field-row scan-form">
        <label class="upload-label">拍摄面单<input type="file" accept="image/*" capture="environment" :disabled="busy" @change="scanPhoto"></label>
        <label class="upload-label">选择面单照片<input type="file" accept="image/*" :disabled="busy" @change="scanPhoto"></label>
      </div>
      <form class="admin-form" @submit.prevent="lookup">
        <label>包裹码<input v-model="code" maxlength="100" autocomplete="off" required @input="parcel = null"></label>
        <button class="button secondary" :disabled="busy">查找包裹</button>
      </form>
      <p v-if="error" class="notice warning" role="alert">{{ error }}</p>
      <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    </section>
    <section v-if="parcel" class="panel scan-result">
      <h2>{{ parcel.code }}</h2>
      <p>{{ parcel.username }} · {{ parcel.shelf }} 货架第 {{ parcel.level }} 层 · 尾号 {{ parcel.suffix }}</p>
      <div class="heading-actions">
        <button class="button primary" type="button" :disabled="busy" @click="finish(false)">确认取件</button>
        <button class="button danger" type="button" :disabled="busy" @click="finish(true)">丢弃包裹</button>
      </div>
    </section>
  </main>
</template>
