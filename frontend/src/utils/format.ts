/** 通用格式化工具。 */

/** 毫秒 → 12:04 / 1:02:03 */
export function formatDuration(ms: number): string {
  if (!ms || ms <= 0) return '--:--'
  const total = Math.floor(ms / 1000)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

/** 秒 → 12:04 / 1:02:03 */
export function formatSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  return formatDuration(Math.floor(seconds) * 1000)
}

/** 字节 → 1.2 MB */
export function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value >= 100 || index === 0 ? Math.round(value) : value.toFixed(1)} ${units[index]}`
}

/** ISO 时间 → 相对时间 */
export function formatRelative(iso: string): string {
  const then = new Date(iso.replace(' ', 'T')).getTime()
  if (Number.isNaN(then)) return iso
  const diff = Date.now() - then
  const minute = 60_000
  const hour = 60 * minute
  const day = 24 * hour
  if (diff < minute) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 30 * day) return `${Math.floor(diff / day)} 天前`
  return new Date(then).toLocaleDateString('zh-CN')
}
