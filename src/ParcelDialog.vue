<script setup>
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { normalizeItem, parseCode, request } from './pickup'

const props = defineProps({
  shelves: { type: Array, required: true },
  existing: { type: Array, required: true },
  initial: { type: Object, default: null },
})
const emit = defineEmits(['added', 'close'])
const dialog = ref()
const method = ref('manual')
const manual = ref(props.initial ? { ...props.initial } : parseCode(''))
const message = ref('')
const image = ref()
const preview = ref('')
const selection = ref(null)
const dragging = ref(false)
const candidates = ref([])
const reading = ref(false)
let cropStart
let ocrRequest

onMounted(() => dialog.value.showModal())
onUnmounted(() => {
  ocrRequest?.abort()
  if (preview.value) URL.revokeObjectURL(preview.value)
})

function selectMethod(value) {
  method.value = value
  message.value = ''
  if (value === 'manual') ocrRequest?.abort()
  nextTick(() => dialog.value.querySelector(value === 'manual' ? '#package-code' : '#screenshot-file')?.focus())
}

function updateManual(value) {
  manual.value = parseCode(value)
  if (!props.shelves.includes(manual.value.shelf)) manual.value.shelf = ''
  message.value = ''
}

function add(items) {
  message.value = ''
  try {
    const rows = items.map(item => normalizeItem(item, props.shelves))
    const existing = new Set(props.existing.map(row => row.code))
    const packages = rows.filter(row => {
      if (existing.has(row.code)) return false
      existing.add(row.code)
      return true
    })
    if (!packages.length) throw new Error('这些货号已在取件清单里。')
    if (props.existing.length + packages.length > 40) throw new Error('本次清单最多可添加 40 件包裹。')
    const duplicateCount = rows.length - packages.length
    emit('added', packages, duplicateCount)
    dialog.value.close()
  } catch (error) {
    message.value = error.message
  }
}

function upload(event) {
  const file = event.target.files?.[0]
  if (!file) return
  ocrRequest?.abort()
  message.value = ''
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 14 * 1024 * 1024) {
    message.value = '请选择 14 MB 以内的 JPG、PNG 或 WebP 图片。'
    return
  }
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = URL.createObjectURL(file)
  selection.value = null
  candidates.value = []
}

function point(event) {
  const bounds = image.value.getBoundingClientRect()
  return [
    Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width)),
    Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height)),
  ]
}

function beginCrop(event) {
  if (event.button !== 0) return
  cropStart = point(event)
  selection.value = null
  dragging.value = true
  event.currentTarget.setPointerCapture(event.pointerId)
}

function moveCrop(event) {
  if (!dragging.value) return
  const [x, y] = point(event)
  selection.value = {
    x: Math.min(x, cropStart[0]),
    y: Math.min(y, cropStart[1]),
    width: Math.abs(x - cropStart[0]),
    height: Math.abs(y - cropStart[1]),
  }
}

function endCrop() {
  dragging.value = false
  if (selection.value?.width < 0.025 || selection.value?.height < 0.025) selection.value = null
}

function croppedImage() {
  const { x, y, width, height } = selection.value ?? { x: 0, y: 0, width: 1, height: 1 }
  const sourceWidth = Math.max(1, width * image.value.naturalWidth)
  const sourceHeight = Math.max(1, height * image.value.naturalHeight)
  const scale = Math.min(1, 2400 / Math.max(sourceWidth, sourceHeight))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(sourceWidth * scale))
  canvas.height = Math.max(1, Math.round(sourceHeight * scale))
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = '#fff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(image.value, x * image.value.naturalWidth, y * image.value.naturalHeight, sourceWidth, sourceHeight, 0, 0, canvas.width, canvas.height)
  return new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.9))
}

async function recognize() {
  if (!image.value?.naturalWidth) {
    message.value = '图片尚未加载，请重新选择截图。'
    return
  }
  message.value = ''
  candidates.value = []
  reading.value = true
  ocrRequest = new AbortController()
  try {
    const signal = ocrRequest.signal
    const imageBlob = await croppedImage()
    if (!imageBlob) throw new Error('图片处理失败，请使用另一张截图。')
    const result = await request('/api/ocr', imageBlob, signal)
    candidates.value = result.candidates
    if (!candidates.value.length) message.value = '没有识别到货号。可以重新裁剪或改用手动输入。'
  } catch (error) {
    if (error.name !== 'AbortError') message.value = error.message
  } finally {
    reading.value = false
  }
}
</script>

<template>
  <dialog ref="dialog" class="parcel-dialog" aria-labelledby="dialog-title" @close="emit('close')">
    <div class="dialog-head">
      <div><h2 id="dialog-title">{{ initial ? '编辑包裹' : '添加包裹' }}</h2><p v-if="!initial" class="muted">将取件通知里的包裹加入本次清单。</p></div>
      <button class="icon-button" type="button" aria-label="关闭" @click="dialog.close()">×</button>
    </div>
    <div v-if="!initial" class="segmented" aria-label="包裹录入方式">
      <button type="button" :aria-pressed="method === 'manual'" @click="selectMethod('manual')">手动输入</button>
      <button type="button" :aria-pressed="method === 'ocr'" @click="selectMethod('ocr')">截图识别</button>
    </div>

    <form v-if="method === 'manual'" class="dialog-form" @submit.prevent="add([manual])">
      <label>货号或取件码
        <input id="package-code" :value="manual.code" maxlength="40" placeholder="例如 C2-01-6721" required @input="updateManual($event.target.value)">
      </label>
      <div class="field-row">
        <label>货架<select v-model="manual.shelf" required><option value="" disabled>选择货架</option><option v-for="shelf in shelves" :key="shelf">{{ shelf }}</option></select></label>
        <label>层号<input v-model="manual.level" inputmode="numeric" maxlength="2" placeholder="选填"></label>
        <label>面单尾号<input v-model="manual.suffix" inputmode="numeric" maxlength="4" placeholder="选填"></label>
      </div>
      <div v-if="message" class="notice warning" role="alert">{{ message }}</div>
      <button class="button primary full" type="submit">{{ initial ? '保存包裹' : '加入取件清单' }}</button>
    </form>

    <div v-else class="dialog-form">
      <label class="upload-label">选择取件通知截图
        <input id="screenshot-file" type="file" accept="image/png,image/jpeg,image/webp" :disabled="reading" @change="upload">
      </label>
      <template v-if="preview">
        <p class="muted compact">在图片上拖动可选择只识别通知内容。</p>
        <div class="crop-preview" @pointerdown="beginCrop" @pointermove="moveCrop" @pointerup="endCrop" @pointercancel="endCrop">
          <img ref="image" :src="preview" alt="选中的取件通知截图" draggable="false">
          <span v-if="selection" class="crop-selection" :style="{ left: selection.x * 100 + '%', top: selection.y * 100 + '%', width: selection.width * 100 + '%', height: selection.height * 100 + '%' }"></span>
        </div>
        <div class="inline-actions">
          <button class="button secondary" type="button" :disabled="reading || !selection" @click="selection = null">使用整张图</button>
          <button class="button primary" type="button" :disabled="reading" @click="recognize">{{ reading ? '正在识别…' : '识别截图' }}</button>
        </div>
      </template>
      <div v-if="message" class="notice warning" role="alert">{{ message }}</div>
      <form v-if="candidates.length" class="dialog-form" @submit.prevent="add(candidates)">
        <p class="muted compact">核对货号与位置后，再加入本次清单。</p>
        <div v-for="(candidate, index) in candidates" :key="index" class="ocr-candidate">
          <label>识别到的货号<input v-model="candidate.code" required maxlength="40"></label>
          <div class="field-row">
            <label>货架<select v-model="candidate.shelf" required><option value="" disabled>选择货架</option><option v-for="shelf in shelves" :key="shelf">{{ shelf }}</option></select></label>
            <label>层号<input v-model="candidate.level" inputmode="numeric" maxlength="2" placeholder="选填"></label>
            <label>面单尾号<input v-model="candidate.suffix" inputmode="numeric" maxlength="4" placeholder="选填"></label>
          </div>
          <button class="text-button" type="button" @click="candidates.splice(index, 1)">移除此候选</button>
        </div>
        <button class="button primary full" type="submit">确认加入 {{ candidates.length }} 件</button>
      </form>
    </div>
  </dialog>
</template>
