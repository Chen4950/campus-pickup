<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import StationMap from './StationMap.vue'
import { request } from './pickup'

const props = defineProps({ view: String, username: String })
const emit = defineEmits(['navigate'])
const storageKey = 'pickup-progress:' + props.username

const dataset = ref(null)
const setupError = ref('')
const parcels = ref([])
const current = ref('ENT')
const expanded = ref('')
const statusMessage = ref('')
const route = ref(null)
const routeError = ref('')
const routing = ref(false)
const forecast = ref(null)
const forecastError = ref('')
const predicting = ref(false)
const day = ref('')
const earliest = ref('10:00')
const latest = ref('20:00')
const selectedTime = ref('')
const locationOpen = ref(false)
let forecastRequest

const station = computed(() => dataset.value?.station)
const shelves = computed(() => dataset.value?.layout.nodes.filter(node => node.type === 'shelf').map(node => node.id) ?? [])
const pending = computed(() => parcels.value.filter(parcel => parcel.status === 'pending'))
const excludedIds = computed(() => parcels.value.filter(parcel => parcel.status !== 'pending').map(parcel => parcel.id))
const found = computed(() => parcels.value.filter(parcel => parcel.status === 'found'))
const deferred = computed(() => parcels.value.filter(parcel => parcel.status === 'deferred'))
const locationLabel = computed(() => current.value === station.value?.entry_node ? '入口' : `${current.value} 货架`)
const selectedForecast = computed(() => forecast.value?.candidates.find(candidate => candidate.time === selectedTime.value))
const pickedDays = computed(() => {
  if (!day.value || !station.value) return []
  const weekday = new Date(`${day.value}T12:00:00+08:00`).getUTCDay()
  return station.value.operating_hours[weekday === 0 || weekday === 6 ? 'weekend' : 'weekday']
})
const stopGroups = computed(() => {
  const groups = new Map()
  for (const parcel of parcels.value) {
    if (!groups.has(parcel.shelf)) groups.set(parcel.shelf, [])
    groups.get(parcel.shelf).push(parcel)
  }
  const ordered = route.value?.stops.filter(shelf => groups.has(shelf)) ?? []
  const extras = [...groups.keys()].filter(shelf => !ordered.includes(shelf))
  return [...ordered, ...extras].map(shelf => ({
    shelf,
    order: ordered.indexOf(shelf) + 1,
    parcels: groups.get(shelf),
    unfinished: groups.get(shelf).filter(parcel => parcel.status === 'pending').length,
    unreachable: route.value?.unreachable_shelves.includes(shelf),
  }))
})

let syncTimer
let refreshRequest
let saved = {}
try { saved = JSON.parse(localStorage.getItem(storageKey)) ?? {} } catch { /* Storage is optional. */ }

async function refreshParcels() {
  if (refreshRequest) return
  const controller = new AbortController()
  refreshRequest = controller
  try {
    const [stationData, records] = await Promise.all([
      request('/api/station', undefined, controller.signal),
      request('/api/parcels/mine', undefined, controller.signal),
    ])
    if (!dataset.value || JSON.stringify(stationData.layout) !== JSON.stringify(dataset.value.layout)) {
      dataset.value = stationData
      const position = saved.current ?? current.value
      current.value = shelves.value.includes(position) ? position : station.value.entry_node
    }
    const statuses = new Map(parcels.value.map(parcel => [parcel.id, parcel.status]))
    const updated = records.map(parcel => ({
      ...parcel, status: statuses.get(parcel.id) ?? saved.statuses?.[parcel.id] ?? 'pending',
    }))
    if (JSON.stringify(updated) !== JSON.stringify(parcels.value)) parcels.value = updated
    saved = {}
    setupError.value = ''
  } catch (error) {
    if (!controller.signal.aborted) setupError.value = error.message
  } finally {
    refreshRequest = undefined
  }
}

async function initialize() {
  await refreshParcels()
  if (!dataset.value || day.value) return
  day.value = dataset.value.today
  if (dataset.value.current_time >= pickedDays.value[1]) day.value = dataset.value.tomorrow
  const [opening, closing] = pickedDays.value
  earliest.value = opening
  latest.value = closing
  if (props.view === 'forecast') {
    await nextTick()
    getForecast()
  }
}

function changeLocation(shelf) {
  current.value = shelf
  expanded.value = shelf
  locationOpen.value = false
  statusMessage.value = `当前位置已更新为 ${locationLabel.value}。`
}

function updateStatus(target, value) {
  if (value !== 'pending') current.value = target.shelf
  expanded.value = target.shelf
  target.status = value
  statusMessage.value = value === 'deferred' ? '已记录暂未找到。'
    : value === 'found' ? '已标记找到。' : '包裹已重新加入取件路线。'
}

watch(() => props.view, next => {
  if (next === 'forecast' && !forecast.value && !predicting.value && day.value) getForecast()
})

async function getForecast() {
  forecastRequest?.abort()
  const controller = new AbortController()
  forecastRequest = controller
  predicting.value = true
  forecastError.value = ''
  forecast.value = null
  const requested = { day: day.value, earliest: earliest.value, latest: latest.value, excluded_ids: excludedIds.value }
  try {
    forecast.value = await request('/api/forecasts', requested, controller.signal)
    selectedTime.value = forecast.value.candidates[0]?.time ?? ''
  } catch (error) {
    if (!controller.signal.aborted) forecastError.value = error.message
  } finally {
    if (forecastRequest === controller) predicting.value = false
  }
}

function shorterWait(option) {
  if (!forecast.value?.now) return ''
  const minutes = Math.round((forecast.value.now.wait_minutes - option.wait_minutes) * 10) / 10
  if (minutes > 0) return `比现在预计少等 ${minutes} 分钟`
  if (minutes < 0) return `比现在预计多等 ${-minutes} 分钟`
  return '与现在预计等待相同'
}

watch([day, earliest, latest, pending], () => {
  forecastRequest?.abort()
  forecast.value = null
  forecastError.value = ''
})
watch([parcels, current], () => {
  if (!dataset.value) return
  try { localStorage.setItem(storageKey, JSON.stringify({ statuses: Object.fromEntries(parcels.value.map(parcel => [parcel.id, parcel.status])), current: current.value })) } catch { /* Private browsing can disable storage. */ }
}, { deep: true })

watch([dataset, current, pending], async (_, __, onCleanup) => {
  route.value = null
  routeError.value = ''
  routing.value = false
  if (!dataset.value || !parcels.value.length) return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  routing.value = true
  try {
    route.value = await request('/api/routes', { start: current.value, excluded_ids: excludedIds.value }, controller.signal)
    if (!expanded.value && route.value.stops.length) expanded.value = route.value.stops[0]
  } catch (error) {
    if (!controller.signal.aborted) routeError.value = error.message
  } finally {
    if (!controller.signal.aborted) routing.value = false
  }
})

onMounted(() => {
  initialize()
  syncTimer = setInterval(initialize, 15000)
  window.addEventListener('focus', initialize)
})
onUnmounted(() => {
  clearInterval(syncTimer)
  window.removeEventListener('focus', initialize)
  forecastRequest?.abort()
  refreshRequest?.abort()
})
</script>

<template>
  <main class="shell">
    <section v-if="setupError" class="panel startup">
      <h1>暂时无法加载</h1><p>{{ setupError }}</p><button type="button" class="button primary" @click="initialize">重试</button>
    </section>
    <div v-else-if="!dataset" class="panel startup" role="status">正在加载驿站数据…</div>

    <template v-else-if="view === 'route'">
      <section class="page-heading">
        <div>
          <h1>站内取件路线</h1>
          <p>把包裹按货架排好，边走边确认。</p>
        </div>
      </section>

      <div class="workspace">
        <section class="panel map-panel" aria-labelledby="map-heading">
          <div class="panel-heading">
            <div><h2 id="map-heading">驿站平面图</h2><p class="muted">按图上的序号依次取件，最后前往出口核验。</p></div>
            <button type="button" class="location-button" :aria-expanded="locationOpen" @click="locationOpen = !locationOpen">
              <span class="location-dot" aria-hidden="true"></span><span>当前位置<span class="location-value">{{ locationLabel }}</span></span>
            </button>
          </div>
          <form v-if="locationOpen" class="location-form" @submit.prevent="locationOpen = false">
            <label>选择当前所在位置<select :value="current" @change="changeLocation($event.target.value)">
              <option :value="station.entry_node">入口</option>
              <option v-for="shelf in shelves" :key="shelf" :value="shelf">{{ shelf }} 货架</option>
            </select></label>
          </form>

          <StationMap :layout="dataset.layout" :route="route?.path" :stops="route?.stops" :current="current" :deferred="deferred.map(parcel => parcel.shelf)" />
          <div class="map-legend" aria-label="地图图例">
            <span><i class="legend-path"></i>建议路线</span><span><i class="legend-current"></i>当前位置</span><span><i class="legend-deferred"></i>暂未找到</span>
          </div>
          <div v-if="routeError" class="notice warning" role="alert">{{ routeError }}</div>
          <div v-else-if="route?.unreachable_shelves.length" class="notice warning" role="status">暂时无法到达 {{ route.unreachable_shelves.join('、') }}。已显示其余可达取件点。</div>
          <div v-else-if="!parcels.length" class="notice">当前账号暂无待取包裹。</div>
          <div v-else-if="!pending.length && route" class="notice">本次待找清单已处理，可前往出口核验。<span v-if="deferred.length">暂未找到的包裹仍在清单中。</span></div>
          <div class="map-metrics" :aria-busy="routing">
            <div><strong>{{ route?.stops.length ?? '—' }}</strong><span>取件货架</span></div>
            <div><strong>{{ route?.distance_m ?? '—' }}<small v-if="route"> 米</small></strong><span>剩余路线</span></div>
            <div><strong class="positive">{{ route?.saved_m ?? '—' }}<small v-if="route?.saved_m != null"> 米</small></strong><span>比录入顺序少走</span></div>
          </div>
        </section>

        <section class="panel list-panel" aria-labelledby="list-heading">
          <div class="panel-heading">
            <div><h2 id="list-heading">本次取件清单</h2><p class="muted">共 {{ parcels.length }} 件<span v-if="found.length"> · 已找到 {{ found.length }} 件</span></p></div>
            <button type="button" class="text-button neutral" @click="initialize">刷新</button>
          </div>
          <div v-if="parcels.length" class="progress-line" role="progressbar" :aria-valuenow="found.length" :aria-valuemin="0" :aria-valuemax="parcels.length" aria-label="已找到的包裹">
            <span :style="{ width: found.length / parcels.length * 100 + '%' }"></span>
          </div>
          <div v-if="!parcels.length" class="empty-list">
            <h3>暂无待取包裹</h3><p class="muted">包裹入库后会自动显示在这里。</p>
          </div>
          <div v-else class="groups">
            <div v-for="group in stopGroups" :key="group.shelf" class="group" :class="{ 'group-open': expanded === group.shelf }">
              <button type="button" class="group-heading" :aria-expanded="expanded === group.shelf" @click="expanded = expanded === group.shelf ? '' : group.shelf">
                <span class="stop-number" :class="{ inactive: !group.order }">{{ group.order || '·' }}</span>
                <span class="group-name"><strong>{{ group.shelf }} 货架</strong><small>{{ group.unreachable ? '暂不可达' : `${group.parcels.length} 件 · 待找 ${group.unfinished} 件` }}</small></span>
                <span v-if="current === group.shelf" class="tag here">当前位置</span>
                <span v-else-if="group.order === 1" class="tag">下一站</span>
                <span class="chevron" aria-hidden="true"></span>
              </button>
              <div v-if="expanded === group.shelf" class="group-content">
                <button v-if="current !== group.shelf && !group.unreachable" type="button" class="text-button arrived" @click="changeLocation(group.shelf)">我已到 {{ group.shelf }}</button>
                <article v-for="parcel in group.parcels" :key="parcel.id" class="parcel">
                  <div class="parcel-top">
                    <div><strong>{{ parcel.level ? `第 ${Number(parcel.level)} 层` : '层号待确认' }}</strong><span v-if="parcel.suffix" class="parcel-tail">尾号 {{ parcel.suffix }}</span><p>{{ parcel.code }}</p></div>
                    <span v-if="parcel.status !== 'pending'" class="tag" :class="{ deferred: parcel.status === 'deferred' }">{{ parcel.status === 'found' ? '已找到' : '暂未找到' }}</span>
                  </div>
                  <div class="parcel-actions">
                    <template v-if="parcel.status === 'pending'">
                      <button type="button" class="button small primary" @click="updateStatus(parcel, 'found')">已找到</button>
                      <button type="button" class="button small secondary" @click="updateStatus(parcel, 'deferred')">暂未找到</button>
                    </template>
                    <button v-else type="button" class="button small secondary" @click="updateStatus(parcel, 'pending')">{{ parcel.status === 'deferred' ? '重新查找' : '撤销已找到' }}</button>
                  </div>
                </article>
              </div>
            </div>
          </div>
          <div v-if="deferred.length" class="notice warning deferred-summary">暂未找到 {{ deferred.length }} 件，可展开对应货架再次查看。</div>
        </section>
      </div>
    </template>

    <template v-else>
      <section class="page-heading forecast-heading">
        <div><h1>什么时候去取件</h1><p>比较可到站时段的预计等待时间。</p></div>
        <button type="button" class="button secondary" @click="emit('navigate', 'route')">查看取件路线</button>
      </section>
      <div class="workspace forecast-workspace">
        <section class="panel forecast-panel" aria-labelledby="forecast-title">
          <div class="panel-heading"><div><h2 id="forecast-title">选择到站时间范围</h2><p class="muted">营业时间 {{ pickedDays[0] }}–{{ pickedDays[1] }}</p></div></div>
          <form class="forecast-form" @submit.prevent="getForecast">
            <label>到站日期<input v-model="day" type="date" :min="dataset.today" :disabled="predicting" required></label>
            <div class="field-row">
              <label>最早到站<input v-model="earliest" type="time" :disabled="predicting" required></label>
              <label>最晚到站<input v-model="latest" type="time" :disabled="predicting" required></label>
            </div>
            <button type="submit" class="button primary full" :disabled="predicting">{{ predicting ? '正在查询…' : '比较到站时段' }}</button>
          </form>
          <div v-if="forecastError" class="notice warning" role="alert">{{ forecastError }}</div>
          <div v-if="forecast && selectedForecast" class="timing-summary">
            <h3>{{ selectedForecast.time }} 到站</h3>
            <div class="timing-row"><span>预计排队</span><strong>{{ selectedForecast.wait_minutes }} 分钟</strong></div>
            <template v-if="selectedForecast.total_minutes !== null">
              <div class="timing-row"><span>步行</span><span>{{ selectedForecast.walk_minutes }} 分钟</span></div>
              <div class="timing-row"><span>找件</span><span>{{ selectedForecast.search_minutes }} 分钟</span></div>
              <div class="timing-row"><span>核验</span><span>{{ selectedForecast.service_minutes }} 分钟</span></div>
              <div class="timing-row total"><strong>预计全程</strong><strong>{{ selectedForecast.total_minutes }} 分钟</strong></div>
              <p class="muted compact">用本次待找清单估算。步行按 {{ forecast.assumptions.walk_m_per_minute }} 米/分钟、找件按 {{ forecast.assumptions.find_min_per_parcel }} 分钟/件计算。</p>
              <p v-if="selectedForecast.may_finish_after_close" class="notice warning">预计离站时间可能晚于关门，建议提前到站。</p>
            </template>
            <p v-else class="muted compact">有待取包裹时会估算站内全程耗时。</p>
          </div>
        </section>
        <section class="panel options-panel" aria-labelledby="candidate-title">
          <div class="panel-heading"><div><h2 id="candidate-title">可选到站时段</h2><p class="muted">按预计等待从短到长排列。</p></div></div>
          <div v-if="predicting" class="notice" role="status">正在比较可用时段…</div>
          <div v-else-if="forecast?.message" class="notice" role="status">{{ forecast.message }}</div>
          <div v-else-if="!forecast" class="notice">选择日期与时间范围后查询。</div>
          <div v-if="forecast?.candidates.length" class="forecast-options">
            <button v-for="(option, index) in forecast.candidates" :key="option.time" type="button" class="slot-option" :class="{ 'slot-selected': selectedTime === option.time }" :aria-pressed="selectedTime === option.time" @click="selectedTime = option.time">
              <span class="slot-copy"><strong>{{ option.time }}</strong><span v-if="index === 0" class="tag">等待最短</span><small>{{ shorterWait(option) || option.basis }}</small></span>
              <span class="slot-measure"><strong>{{ option.wait_minutes }} <small>分钟</small></strong><small>常见 {{ option.usual_low_minutes }}–{{ option.usual_high_minutes }} 分钟</small></span>
            </button>
          </div>
          <p v-if="forecast?.latest_sample" class="muted forecast-source">基于合成历史观测 · 样本截至 {{ forecast.latest_sample }}。</p>
        </section>
      </div>
    </template>
    <p v-if="dataset" class="data-footer"><span class="data-dot"></span>课程原型 · 合成数据</p>
    <p class="sr-only" aria-live="polite">{{ statusMessage }}</p>
  </main>

</template>
