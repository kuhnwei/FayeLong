<script setup lang="ts">
/**
 * 生词本页（照搬旧 `frontend/src/pages/VocabPage.tsx`，363 行）。
 *
 * 覆盖：列表 / 全部·待复习·已掌握 筛选 / 搜索 / 逐条朗读 / 编辑释义 /
 * 标记已掌握 / 删除确认 / 导出 Markdown / 进入练习页。
 *
 * 与旧版的等价性说明：
 * - `useDeferredValue(keyword)` 在 Vue 里没有对应物：这里直接把 `keyword` 放进 queryKey，
 *   vue-query 会随输入自动重新请求（旧版的语义就是「输入即搜索」，行为一致）。
 * - 旧版内联的 `VocabRow` 拆成独立 SFC `components/VocabRow.vue`（DOM 逐字保留）。
 * - `isLoading` / `isError` 与旧版同名同义（无数据 + 首次请求中才显示「加载中…」）。
 */
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { deleteVocab, listVocab, updateVocab, vocabExportUrl } from '../api/client'
import type { VocabItem } from '../api/client'
import VocabRow from '../components/VocabRow.vue'
import { BookIcon, DownloadIcon, SearchIcon, TargetIcon } from '../components/icons'

type Filter = 'all' | 'todo' | 'mastered'

const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'todo', label: '待复习' },
  { key: 'mastered', label: '已掌握' },
]

const queryClient = useQueryClient()

const filter = ref<Filter>('all')
const keyword = ref('')

const queryKey = computed(() => ['vocab', filter.value, keyword.value])
const { data, isLoading, isError, error } = useQuery({
  queryKey,
  queryFn: () =>
    listVocab({
      mastered: filter.value === 'all' ? undefined : filter.value === 'mastered',
      q: keyword.value.trim() || undefined,
    }),
})

const items = computed<VocabItem[]>(() => data.value?.items ?? [])
const errorText = computed(() => (error.value as Error | null)?.message ?? '')

const invalidate = () => {
  void queryClient.invalidateQueries({ queryKey: ['vocab'] })
}

const toggleMutation = useMutation({
  mutationFn: (vars: { id: number; mastered: boolean }) =>
    updateVocab(vars.id, { mastered: vars.mastered }),
  onSuccess: invalidate,
})

const editMutation = useMutation({
  mutationFn: (vars: { id: number; translation: string }) =>
    updateVocab(vars.id, { translation: vars.translation }),
  onSuccess: invalidate,
})

const deleteMutation = useMutation({
  mutationFn: (id: number) => deleteVocab(id),
  onSuccess: invalidate,
})

const busy = computed(
  () =>
    toggleMutation.isPending.value ||
    editMutation.isPending.value ||
    deleteMutation.isPending.value,
)

/** 有释义的词才能参与练习（中译英需要中文题干，英译中需要正确选项） */
const practisable = computed(
  () => items.value.filter((item) => (item.translation ?? '').trim()).length,
)

/** D3 统计四卡：口径统一为「当前列表」，避免筛选后数字互相矛盾 */
const viewStats = computed(() => ({
  total: items.value.length,
  todo: items.value.filter((item) => !item.mastered).length,
  mastered: items.value.filter((item) => item.mastered).length,
  practisable: practisable.value,
}))

function onToggleMastered(item: VocabItem) {
  toggleMutation.mutate({ id: item.id, mastered: !item.mastered })
}

function onSaveTranslation(item: VocabItem, translation: string) {
  editMutation.mutate({ id: item.id, translation })
}

function onDelete(item: VocabItem) {
  if (window.confirm(`确定从生词本删除「${item.lemma || item.word}」？`)) {
    deleteMutation.mutate(item.id)
  }
}
</script>

<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-[15px] font-medium text-ink">生词本</h2>
        <p class="mt-1 text-[13px] text-ink-2">
          学习页中点击单词可查词并一键收藏，这里集中复习、管理，也可以做练习。
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <RouterLink
          to="/vocab/practice"
          :title="practisable < 2 ? '至少需要 2 个带释义的生词' : '开始中译英 / 英译中练习'"
          :class="[
            'flex items-center gap-1.5 rounded-full border-2 border-ink px-4 py-2.5 text-[13px] font-bold transition-transform',
            practisable >= 2
              ? 'bg-white text-ink hover:-translate-y-px hover:shadow-[0_3px_0_var(--ink)] active:translate-y-[2px] active:shadow-none'
              : 'pointer-events-none bg-white text-ink-3',
          ]"
        >
          <TargetIcon class-name="h-3.5 w-3.5" />
          开始练习
          <span v-if="practisable >= 2" class="tabular-nums text-ink-3">{{ practisable }}</span>
        </RouterLink>
        <a
          :href="vocabExportUrl(filter === 'mastered' ? true : undefined)"
          :class="[
            'flex items-center gap-1.5 rounded-full border-2 border-ink px-4 py-2.5 text-[13px] font-bold shadow-[0_3px_0_var(--ink)] transition-transform',
            items.length
              ? 'bg-lemon-400 text-ink hover:-translate-y-px hover:bg-lemon-300 active:translate-y-[3px] active:shadow-none'
              : 'pointer-events-none border-cream-2 bg-cream-2 text-ink-2 shadow-none',
          ]"
        >
          <DownloadIcon class-name="h-3.5 w-3.5" />
          导出 Markdown
        </a>
      </div>
    </div>

    <!-- 统计四卡（D3）：口径 = 当前列表 -->
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <div class="rounded-xl border-2 border-ink bg-white px-3.5 py-2.5">
        <span class="block text-[11.5px] text-ink-3">当前列表</span>
        <b class="mt-0.5 block text-[21px] font-extrabold leading-tight tabular-nums text-ink">
          {{ viewStats.total }}<small class="ml-0.5 text-[11px] font-semibold text-ink-3">个</small>
        </b>
      </div>
      <div class="rounded-xl border-2 border-ink bg-white px-3.5 py-2.5">
        <span class="block text-[11.5px] text-ink-3">待复习</span>
        <b class="mt-0.5 block text-[21px] font-extrabold leading-tight tabular-nums text-ink">
          {{ viewStats.todo }}<small class="ml-0.5 text-[11px] font-semibold text-ink-3">个</small>
        </b>
      </div>
      <div class="rounded-xl border-2 border-ink bg-white px-3.5 py-2.5">
        <span class="block text-[11.5px] text-ink-3">已掌握</span>
        <b class="mt-0.5 block text-[21px] font-extrabold leading-tight tabular-nums text-emerald-600">
          {{ viewStats.mastered }}<small class="ml-0.5 text-[11px] font-semibold text-ink-3">个</small>
        </b>
      </div>
      <div class="rounded-xl border-2 border-ink bg-lemon-100 px-3.5 py-2.5">
        <span class="block text-[11.5px] text-ink-3">可练习</span>
        <b class="mt-0.5 block text-[21px] font-extrabold leading-tight tabular-nums text-ink">
          {{ viewStats.practisable }}<small class="ml-0.5 text-[11px] font-semibold text-ink-3">个</small>
        </b>
      </div>
    </div>

    <!-- 工具条（D3）：药丸 chips + 搜索 -->
    <div class="flex flex-wrap items-center gap-2 sm:gap-3">
      <div class="flex flex-1 items-center gap-2 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <button
          v-for="item in FILTERS"
          :key="item.key"
          type="button"
          :data-selected="filter === item.key ? 'true' : 'false'"
          :class="[
            'shrink-0 rounded-full border-2 px-3.5 py-1.5 text-[12.5px] font-bold transition-colors',
            filter === item.key
              ? 'border-ink bg-lemon-400 text-ink'
              : 'border-ink/25 bg-white text-ink-2 hover:border-ink/50 hover:text-ink',
          ]"
          @click="filter = item.key"
        >
          {{ item.label }}
        </button>
      </div>

      <div class="relative w-full sm:ml-auto sm:w-[220px]">
        <SearchIcon
          class-name="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3"
        />
        <input
          v-model="keyword"
          placeholder="搜索单词或释义…"
          class="w-full rounded-full border-2 border-ink/25 py-1.5 pl-8 pr-3 text-[12.5px] text-ink outline-none transition-colors focus:border-ink"
        />
      </div>
    </div>

    <p
      v-if="isLoading"
      class="rounded-2xl border-2 border-ink bg-white px-3 py-8 text-center text-[13px] text-ink-3 sm:px-5"
    >
      加载中…
    </p>

    <p
      v-if="isError"
      class="rounded-xl border border-red-100 bg-red-50 px-3 py-8 text-center text-[13px] text-red-600 sm:px-5"
    >
      {{ errorText }}
    </p>

    <div
      v-if="!isLoading && !isError && items.length === 0"
      class="rounded-2xl border-2 border-ink bg-white px-3 py-12 text-center sm:px-5"
    >
      <BookIcon class-name="mx-auto h-8 w-8 text-ink-3" />
      <p class="mt-3 text-[13px] text-ink-3">
        {{
          keyword || filter !== 'all'
            ? '没有符合条件的生词。'
            : '还没有生词。到学习页点击原文里的单词，即可查词并加入生词本。'
        }}
      </p>
    </div>

    <div
      v-if="!isLoading && !isError && items.length > 0"
      class="overflow-hidden rounded-2xl border-2 border-ink bg-white"
    >
      <!-- 表头（PC only） -->
      <div
        class="hidden grid-cols-[minmax(0,1.05fr)_minmax(0,1.45fr)_minmax(0,.95fr)_88px_96px] items-center gap-3 border-b-2 border-ink bg-cream-2 px-4 py-2 text-[11px] font-bold tracking-[0.4px] text-ink-3 sm:grid"
      >
        <span>单词</span>
        <span>释义</span>
        <span>出处</span>
        <span class="text-center">状态</span>
        <span class="text-right">操作</span>
      </div>

      <VocabRow
        v-for="item in items"
        :key="item.id"
        :item="item"
        :busy="busy"
        @toggle-mastered="onToggleMastered(item)"
        @save-translation="(translation) => onSaveTranslation(item, translation)"
        @delete="onDelete(item)"
      />
    </div>
  </div>
</template>
