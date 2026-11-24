/**
 * 运行时 API 基址解析。
 *
 * 前端产物构建一次即可部署到任意机器：部署时通过 window.__YUXI_API_BASE__
 * 指定后端地址，无需重新构建。
 *
 * 只认这一个来源，刻意不读 VITE_API_URL——该变量在 Vuxi 里的既有语义是
 * 「dev server 的反向代理目标」，浏览器拿到它会把请求直连后端，
 * 既绕过代理又需要后端放开 CORS。开发期应让请求走相对路径，由 vite 代理转发。
 *
 * 取值优先级：
 * 1. window.__YUXI_API_BASE__（部署时注入，跨机器部署的主力方式）
 * 2. 空字符串（同源请求，由 Nginx 或 vite dev server 反向代理到后端）
 *
 * 该值在应用启动时读取一次并缓存，避免运行中切换导致会话状态不一致。
 */

const RUNTIME_BASE_KEY = '__YUXI_API_BASE__'

let cachedBaseUrl = null

/** 去掉末尾斜杠，避免与以 / 开头的路径拼接出双斜杠。 */
function normalizeBaseUrl(value) {
  const trimmed = String(value || '').trim()
  if (!trimmed) return ''
  return trimmed.replace(/\/+$/, '')
}

/** 读取部署注入的 API 基址；window 在 SSR/测试环境可能不存在。 */
export function resolveApiBaseUrl() {
  if (cachedBaseUrl !== null) return cachedBaseUrl

  let base = ''
  if (typeof window !== 'undefined') {
    base = normalizeBaseUrl(window[RUNTIME_BASE_KEY])
  }

  cachedBaseUrl = base
  return cachedBaseUrl
}

/**
 * 把相对路径转换为可请求的绝对地址。
 * 已经是绝对地址的输入原样返回。
 */
export function withApiBase(path) {
  const target = String(path || '')
  if (!target || /^https?:\/\//i.test(target)) return target
  const base = resolveApiBaseUrl()
  if (!base) return target
  return `${base}${target.startsWith('/') ? '' : '/'}${target}`
}

/** 仅用于测试与开发环境的基址重置。 */
export function resetApiBaseUrlCache() {
  cachedBaseUrl = null
}
