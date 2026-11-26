<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  layout: { type: Object, required: true },
  route: { type: Array, default: () => [] },
  stops: { type: Array, default: () => [] },
  current: { type: String, default: 'ENT' },
  deferred: { type: Array, default: () => [] },
})

const canvas = ref()
let observer

function paint() {
  if (!canvas.value) return
  const surface = canvas.value
  const width = surface.clientWidth
  const height = surface.clientHeight
  if (!width || !height) return
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
  surface.width = Math.round(width * pixelRatio)
  surface.height = Math.round(height * pixelRatio)
  const ctx = surface.getContext('2d')
  ctx.scale(pixelRatio, pixelRatio)
  ctx.clearRect(0, 0, width, height)

  const inset = width < 460 ? 36 : 58
  const xValues = props.layout.nodes.map(node => node.x)
  const yValues = props.layout.nodes.map(node => node.y)
  const xMin = Math.min(...xValues)
  const yMin = Math.min(...yValues)
  const xSpan = Math.max(1, Math.max(...xValues) - xMin)
  const ySpan = Math.max(1, Math.max(...yValues) - yMin)
  const points = Object.fromEntries(props.layout.nodes.map(node => [
    node.id,
    [inset + (node.x - xMin) / xSpan * (width - 2 * inset), height * 0.64 - (node.y - yMin) / ySpan * height * 0.30],
  ]))

  ctx.strokeStyle = '#dce6e5'
  ctx.fillStyle = '#f9fbfb'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.roundRect(12, 12, width - 24, height - 24, 19)
  ctx.fill()
  ctx.stroke()
  ctx.save()
  ctx.clip()
  ctx.fillStyle = '#e6eeed'
  for (let x = 24; x < width - 15; x += 16) {
    for (let y = 24; y < height - 15; y += 16) {
      ctx.beginPath()
      ctx.arc(x, y, 0.8, 0, Math.PI * 2)
      ctx.fill()
    }
  }
  ctx.restore()

  function line(a, b) {
    if (!points[a] || !points[b]) return
    ctx.beginPath()
    ctx.moveTo(...points[a])
    ctx.lineTo(...points[b])
    ctx.stroke()
  }

  const pairs = new Set()
  ctx.lineCap = 'round'
  ctx.strokeStyle = '#dbe6e4'
  ctx.lineWidth = 10
  for (const edge of props.layout.directed_edges) {
    const pair = [edge.from, edge.to].sort().join(':')
    if (pairs.has(pair)) continue
    pairs.add(pair)
    line(edge.from, edge.to)
  }
  ctx.strokeStyle = '#1e866e'
  ctx.lineWidth = 5
  props.route.slice(1).forEach((node, index) => line(props.route[index], node))

  const small = width < 460
  const labelSize = small ? 11 : 13
  const shelfWidth = small ? 38 : 53
  const shelfHeight = small ? 24 : 31
  const lastArrowSegment = props.route.length - 2
  for (let index = 0; index <= lastArrowSegment; index++) {
    const start = points[props.route[index]]
    const end = points[props.route[index + 1]]
    if (Math.hypot(end[0] - start[0], end[1] - start[1]) < 32) continue
    const x = (start[0] + end[0]) / 2
    const y = (start[1] + end[1]) / 2
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(Math.atan2(end[1] - start[1], end[0] - start[0]))
    ctx.strokeStyle = '#ffffff'
    ctx.lineWidth = 1.6
    ctx.beginPath()
    ctx.moveTo(-2, -2.6)
    ctx.lineTo(1.5, 0)
    ctx.lineTo(-2, 2.6)
    ctx.stroke()
    ctx.restore()
  }

  for (const node of props.layout.nodes) {
    const [x, y] = points[node.id]
    const current = node.id === props.current
    const order = props.stops.indexOf(node.id)
    const active = order >= 0
    const onPath = props.route.includes(node.id)
    const isShelf = node.type === 'shelf'
    const deferred = props.deferred.includes(node.id)
    const below = node.y === yMin
    if (isShelf) {
      const top = below ? y + 14 : y - shelfHeight - 14
      ctx.fillStyle = current || active ? '#d9eee8' : deferred ? '#fdf0d6' : '#eaf0ef'
      ctx.strokeStyle = current || active ? '#a5d3c6' : deferred ? '#ead4a7' : '#dce6e5'
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.roundRect(x - shelfWidth / 2, top, shelfWidth, shelfHeight, 6)
      ctx.fill()
      ctx.stroke()
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillStyle = current || active ? '#185f50' : '#45605d'
      ctx.font = `700 ${labelSize}px system-ui, sans-serif`
      ctx.fillText(node.id, x, top + shelfHeight / 2)
    }

    const radius = current ? 9 : active ? 9 : isShelf ? 4 : 6
    ctx.fillStyle = current ? '#0b5042' : active || onPath ? '#1e866e' : '#8fa6a3'
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.arc(x, y, radius, 0, Math.PI * 2)
    ctx.fill()
    ctx.stroke()
    if (active) {
      ctx.font = '700 10px system-ui, sans-serif'
      ctx.fillStyle = '#fff'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(String(order + 1), x, y)
    } else if (current) {
      ctx.beginPath()
      ctx.arc(x, y, 2.7, 0, Math.PI * 2)
      ctx.fillStyle = '#fff'
      ctx.fill()
    }
    if (!isShelf) {
      ctx.font = `600 ${labelSize}px system-ui, sans-serif`
      ctx.fillStyle = '#4e6663'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText({ entrance: '入口', verification: '核验', exit: '出口' }[node.type], x, y + 25)
    }
  }
}

onMounted(() => {
  observer = new ResizeObserver(paint)
  observer.observe(canvas.value)
  paint()
})
onUnmounted(() => observer?.disconnect())
watch(() => [props.layout, props.route, props.stops, props.current, props.deferred], paint)
</script>

<template>
  <canvas ref="canvas" class="station-canvas" role="img" :aria-label="`驿站平面图，取件顺序 ${stops.join('、') || '暂无取件点'}`"></canvas>
</template>
