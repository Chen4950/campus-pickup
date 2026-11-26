export async function request(path, body, signal, method = body === undefined ? 'GET' : 'POST') {
  const image = body instanceof Blob
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': image ? body.type : 'application/json' },
    body: body === undefined || image ? body : JSON.stringify(body),
    signal,
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const error = new Error(typeof data.detail === 'string' ? data.detail : '请求失败，请核对输入后重试。')
    error.status = response.status
    if (error.status === 401 && !['/api/auth/me', '/api/auth/login', '/api/auth/register'].includes(path)) {
      window.dispatchEvent(new Event('pickup-session-expired'))
    }
    throw error
  }
  return data
}

export function parseCode(value) {
  const code = value.normalize('NFKC').trim().toUpperCase().replace(/\s*[-‐–—·]\s*/g, '-')
  const [, shelf = '', level = '', suffix = ''] = /^([A-Z][0-9]{1,3})-([0-9]{1,2})-([0-9]{4})$/.exec(code) ?? []
  return { code, shelf, level, suffix }
}

export function normalizeItem(item, shelves) {
  const code = item.code.trim().normalize('NFKC').toUpperCase()
  const level = item.level.trim()
  const suffix = item.suffix.trim()
  if (!code || code.length > 40) throw new Error('请输入 1–40 个字符的货号或识别码。')
  if (!shelves.includes(item.shelf)) throw new Error('请为该包裹选择实际货架。')
  if (level && !/^\d{1,2}$/.test(level)) throw new Error('层号应为 1–2 位数字。')
  if (suffix && !/^\d{4}$/.test(suffix)) throw new Error('面单尾号应为 4 位数字。')
  return { code, shelf: item.shelf, level, suffix, status: 'pending' }
}
