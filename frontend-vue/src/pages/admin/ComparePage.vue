<script setup lang="ts">
/**
 * 管理员「学习状态对比」页（v1.16.2）。
 *
 * 每个用户一张卡片，横向对比其学习统计（听写 / 正确率 / 生词 / 笔记 / 连续天数）。
 */
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { listAdminUsers, type AdminUserOut } from '../../api/client'

const { data, isLoading, isError, error } = useQuery({
  queryKey: ['admin', 'users'],
  queryFn: listAdminUsers,
})

const items = computed<AdminUserOut[]>(() => data.value?.items ?? [])
const errorText = computed(() => (error.value as Error)?.message ?? '加载失败')

const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v)}%`)
const roleLabel = (role: string) => (role === 'admin' ? '管理员' : '普通用户')
</script>

<template>
  <div class="space-y-4">
    <div>
      <h2 class="text-[18px] font-extrabold text-ink">学习状态对比</h2>
      <p class="mt-0.5 text-[12px] text-ink-3">各用户的听写、生词、笔记与连续学习情况</p>
    </div>

    <p v-if="isLoading" class="rounded-2xl border-2 border-ink bg-white px-3 py-8 text-center text-[13px] text-ink-3">
      加载中…
    </p>
    <p v-else-if="isError" class="rounded-xl border border-red-100 bg-red-50 px-3 py-8 text-center text-[13px] text-red-600">
      {{ errorText }}
    </p>

    <div v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div
        v-for="u in items"
        :key="u.id"
        class="rounded-2xl border-2 border-ink bg-white p-4"
      >
        <div class="flex items-center gap-2">
          <span class="text-[14px] font-extrabold text-ink">{{ u.username }}</span>
          <span
            class="rounded-full px-2 py-0.5 text-[10.5px] font-semibold"
            :class="u.role === 'admin' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600'"
          >
            {{ roleLabel(u.role) }}
          </span>
          <span
            v-if="!u.is_active"
            class="rounded-full bg-red-100 px-2 py-0.5 text-[10.5px] font-semibold text-red-600"
          >
            已停用
          </span>
        </div>

        <div class="mt-3 grid grid-cols-3 gap-2">
          <div class="rounded-lg bg-cream-2 px-2.5 py-2">
            <span class="block text-[10.5px] text-ink-3">听写次数</span>
            <b class="block text-[17px] font-extrabold tabular-nums text-ink">{{ u.stats.attempts_total }}</b>
          </div>
          <div class="rounded-lg bg-cream-2 px-2.5 py-2">
            <span class="block text-[10.5px] text-ink-3">平均正确率</span>
            <b class="block text-[17px] font-extrabold tabular-nums text-ink">{{ pct(u.stats.attempts_avg_accuracy) }}</b>
          </div>
          <div class="rounded-lg bg-cream-2 px-2.5 py-2">
            <span class="block text-[10.5px] text-ink-3">连续天数</span>
            <b class="block text-[17px] font-extrabold tabular-nums text-ink">{{ u.stats.streak_days }}</b>
          </div>
          <div class="rounded-lg bg-cream-2 px-2.5 py-2">
            <span class="block text-[10.5px] text-ink-3">生词</span>
            <b class="block text-[17px] font-extrabold tabular-nums text-ink">
              {{ u.stats.vocab_total }}<small class="text-[10px] text-ink-3">/{{ u.stats.vocab_mastered }}</small>
            </b>
          </div>
          <div class="rounded-lg bg-cream-2 px-2.5 py-2">
            <span class="block text-[10.5px] text-ink-3">笔记</span>
            <b class="block text-[17px] font-extrabold tabular-nums text-ink">{{ u.stats.notes_count }}</b>
          </div>
          <div class="rounded-lg bg-cream-2 px-2.5 py-2">
            <span class="block text-[10.5px] text-ink-3">作答会话</span>
            <b class="block text-[17px] font-extrabold tabular-nums text-ink">{{ u.stats.sessions_total }}</b>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
