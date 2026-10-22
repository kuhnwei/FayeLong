/**
 * 统计页 API（P2）。
 *
 * 类型与 `backend/app/schemas/stats.py::OverviewOut` 对齐。
 * `created_at` 后端返回 ISO 字符串，前端不做时区换算（单机自用，ARCH §8 日期口径）。
 */
import { request } from './request'

export interface DailyPoint {
  date: string
  attempts: number
  accuracy: number
  new_vocab: number
}

export interface StatsOverview {
  days: number
  daily: DailyPoint[]
  kpi: {
    today_attempts: number
    today_accuracy: number
    today_new_vocab: number
    streak_days: number
  }
  courses: {
    media_id: number
    title: string
    total: number
    attempted: number
    pct: number
  }[]
  recent: {
    sentence_text: string
    created_at: string
    accuracy: number
  }[]
  vocab: {
    total: number
    mastered: number
  }
}

export const getOverview = (days = 14) =>
  request<StatsOverview>(`/stats/overview?days=${days}`)
