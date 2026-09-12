/**
 * 时间格式化。
 *
 * 后端返回的 creat_time / update_time 是 MySQL 的无时区字符串（Docker 容器默认 UTC），
 * 形如 "2026-09-12T03:00:00" 或 "2026-09-12T03:00:00.123456"。
 * JS 的 Date 会把无时区字符串当**本地时间**解析，这里统一补 Z 视为 UTC，
 * 再截断到毫秒（V8 不接受 6 位小数，会得到 Invalid Date）。
 */
export function parseServerTime(v) {
  if (!v) return null
  if (v instanceof Date) return Number.isNaN(v.getTime()) ? null : v
  const s = String(v)
    .replace(' ', 'T')
    .replace(/(\.\d{3})\d+/, '$1')   // 2026-…T03:00:00.123456 -> …T03:00:00.123
  const iso = /[zZ]|[+-]\d{2}:?\d{2}$/.test(s) ? s : `${s}Z`
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

const pad = (n) => String(n).padStart(2, '0')

/** 24 小时制时钟，如 09:05 */
export function fmtClock(v) {
  const d = parseServerTime(v)
  if (!d) return ''
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 相对时间，如 刚刚 / 12 分钟前 / 3 小时前 / 2 天前 / 9月3日 */
export function fmtAgo(v) {
  const d = parseServerTime(v)
  if (!d) return ''
  const diff = Date.now() - d.getTime()
  if (diff < 0) return fmtClock(d)
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`
  const y = d.getFullYear() === new Date().getFullYear() ? '' : `${d.getFullYear()}年`
  return `${y}${d.getMonth() + 1}月${d.getDate()}日`
}
