<script setup lang="ts">
/**
 * 「管理分类」面板（照搬旧 `CategoryManager.tsx`）：新建 / 行内重命名 / 删除（回落未分类）/ ↑↓ 排序。
 *
 * 形态：桌面居中弹层，窄屏贴底（bottom sheet）。三段式外壳下用 fixed 覆盖，不动布局高度。
 * 排序**不做拖拽**（新依赖 + 移动端误触），用 ↑/↓ 按钮 —— 点击后本地先重排，再把**整份顺序**提交。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useMutation } from '@tanstack/vue-query'
import {
  createCategory,
  deleteCategory,
  reorderCategories,
  updateCategory,
  type CategoryItem,
} from '../api/client'
import { ChevronDownIcon, ChevronUpIcon, CloseIcon, PencilIcon, TrashIcon } from './icons'

const NAME_MAX = 32

/** 按「字符」计数（CJK 与 emoji 都各算 1），与后端 1–32 的口径对齐 */
const charLength = (value: string) => [...value].length

/** 把后端错误转成人话；同名冲突统一显示规格里写死的那句 */
function errorText(error: Error): string {
  const message = error.message || ''
  if (/存在|同名|unique/i.test(message)) return '已存在同名分类'
  if (/不能为空|必填/.test(message)) return '分类名不能为空'
  if (/过长|长度|32/.test(message)) return `分类名不能超过 ${NAME_MAX} 个字符`
  return message || '操作失败，请稍后重试'
}

/** 两份分类列表是否「看起来一样」（id 顺序 + 名字 + 计数），用于避免无意义的状态重置 */
function sameCategories(a: CategoryItem[], b: CategoryItem[]): boolean {
  if (a === b) return true
  if (a.length !== b.length) return false
  return a.every(
    (item, i) =>
      item.id === b[i].id && item.name === b[i].name && item.media_count === b[i].media_count,
  )
}

interface Props {
  items: CategoryItem[]
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'close'): void
  /** 数据变了（新建/改名/删除/排序）——调用方去 invalidate ['categories'] 与 ['media'] */
  (e: 'changed'): void
  (e: 'notify', text: string, tone?: 'info' | 'error'): void
}>()

// 本地副本：点 ↑/↓ 后先动它，避免等网络往返才看到位移。
// 同步时比较内容而不是引用 —— 父级若给出「每次渲染都是新数组」的 items，
// 只按引用同步会让这里无限重渲染。
const local = ref<CategoryItem[]>(props.items)
watch(
  () => props.items,
  (items) => {
    local.value = sameCategories(local.value, items) ? local.value : items
  },
)

const draft = ref('')
const createError = ref<string | null>(null)

const editingId = ref<number | null>(null)
const editDraft = ref('')
const editError = ref<string | null>(null)

// Esc 关闭面板（行内编辑时让 Esc 先给输入框用）
function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && editingId.value === null) emit('close')
}
onMounted(() => document.addEventListener('keydown', onKey))
onUnmounted(() => document.removeEventListener('keydown', onKey))

// 重命名输入框是动态渲染的：`autofocus` 属性对 DOM API 插入的元素无效，须显式 focus
const vFocus = { mounted: (el: HTMLElement) => el.focus() }

const createMutation = useMutation({
  mutationFn: (name: string) => createCategory(name),
  onSuccess: () => {
    draft.value = ''
    createError.value = null
    emit('changed')
  },
  onError: (error: Error) => {
    createError.value = errorText(error)
  },
})

const renameMutation = useMutation({
  mutationFn: ({ id, name }: { id: number; name: string }) => updateCategory(id, name),
  onSuccess: () => {
    editingId.value = null
    editError.value = null
    emit('changed')
  },
  // 撞名不丢输入：重新打开输入框，把已输入的原文留在里面，只在下面红字提示
  onError: (error: Error, variables) => {
    editError.value = errorText(error)
    editingId.value = variables.id
  },
})

const deleteMutation = useMutation({
  mutationFn: (category: CategoryItem) => deleteCategory(category.id),
  onSuccess: (result) => {
    emit('notify', `已删除分类「${result.name}」，${result.released} 个素材已移入「未分类」`)
    emit('changed')
  },
  onError: (error: Error) => emit('notify', `删除失败：${error.message}`, 'error'),
})

const orderMutation = useMutation({
  mutationFn: (ids: number[]) => reorderCategories(ids),
  onSuccess: () => emit('changed'),
  onError: (error: Error) => {
    local.value = props.items
    emit('notify', `排序失败：${error.message}`, 'error')
    emit('changed')
  },
})

const trimmedDraft = computed(() => draft.value.trim())
const draftLength = computed(() => charLength(trimmedDraft.value))
const canCreate = computed(
  () =>
    trimmedDraft.value.length > 0 && draftLength.value <= NAME_MAX && !createMutation.isPending.value,
)
const busy = computed(() => deleteMutation.isPending.value || renameMutation.isPending.value)

function submitCreate() {
  if (!canCreate.value) return
  createError.value = null
  createMutation.mutate(trimmedDraft.value)
}

function startRename(category: CategoryItem) {
  editDraft.value = category.name
  editError.value = null
  editingId.value = category.id
}

function commitRename(category: CategoryItem) {
  const value = editDraft.value.trim()
  editingId.value = null
  editError.value = null
  if (value && value !== category.name) renameMutation.mutate({ id: category.id, name: value })
}

function move(index: number, delta: -1 | 1) {
  const target = index + delta
  if (target < 0 || target >= local.value.length) return
  const next = [...local.value]
  const tmp = next[index]
  next[index] = next[target]
  next[target] = tmp
  local.value = next
  // 契约要求提交**当前全部分类 id 的完整有序集合**
  orderMutation.mutate(next.map((c) => c.id))
}

function confirmDelete(category: CategoryItem) {
  const message = `删除分类「${category.name}」后，其中的 ${category.media_count} 个素材会移入「未分类」，不会被删除。确定删除？`
  if (window.confirm(message)) deleteMutation.mutate(category)
}

</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/40 sm:items-center"
    @click="emit('close')"
  >
    <div
      role="dialog"
      aria-modal="true"
      aria-label="管理分类"
      class="flex max-h-[85dvh] w-full flex-col rounded-t-2xl bg-white shadow-xl sm:max-w-lg sm:rounded-2xl"
      @click.stop
    >
      <div class="flex shrink-0 items-center justify-between border-b border-slate-100 px-4 py-3 sm:px-5">
        <h3 class="text-[14px] font-medium text-slate-900">管理分类</h3>
        <button
          type="button"
          aria-label="关闭"
          class="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
          @click="emit('close')"
        >
          <CloseIcon class-name="h-4 w-4" />
        </button>
      </div>

      <!-- 新建 -->
      <div class="shrink-0 border-b border-slate-100 px-4 py-3 sm:px-5">
        <div class="flex items-center gap-2">
          <input
            v-model="draft"
            :placeholder="`新分类名（1–${NAME_MAX} 个字）`"
            aria-label="新分类名"
            class="h-9 min-w-0 flex-1 rounded-lg border border-slate-300 px-3 text-[13px] text-slate-800 outline-none transition-colors focus:border-slate-500"
            @keydown.enter="submitCreate"
            @input="createError = null"
          />
          <button
            type="button"
            :disabled="!canCreate"
            class="h-9 shrink-0 rounded-lg bg-slate-900 px-4 text-[13px] text-white transition-colors hover:bg-slate-700 disabled:opacity-40"
            @click="submitCreate"
          >
            {{ createMutation.isPending.value ? '新建中…' : '新建' }}
          </button>
        </div>
        <div class="mt-1 space-y-0.5">
          <p v-if="draft.length > 0 && trimmedDraft.length === 0" class="text-[11px] text-red-600">
            分类名不能为空
          </p>
          <p v-if="draftLength > NAME_MAX" class="text-[11px] text-red-600">
            分类名不能超过 {{ NAME_MAX }} 个字符（当前 {{ draftLength }} 个）
          </p>
          <p v-if="createError" class="text-[11px] text-red-600">{{ createError }}</p>
        </div>
      </div>

      <!-- 列表 -->
      <div class="min-h-0 flex-1 overflow-y-auto px-2 py-2 sm:px-3">
        <p v-if="local.length === 0" class="px-3 py-8 text-center text-[13px] text-slate-400">
          还没有分类。上面输入一个名字，建好后就能把素材归进去。
        </p>

        <div
          v-for="(category, index) in local"
          :key="category.id"
          class="flex items-center gap-1.5 rounded-lg px-1.5 py-1.5 hover:bg-slate-50"
        >
          <div class="flex shrink-0 flex-col">
            <button
              type="button"
              :disabled="index === 0 || orderMutation.isPending.value"
              :title="'上移'"
              :aria-label="`将「${category.name}」上移`"
              class="flex h-8 w-8 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
              @click="move(index, -1)"
            >
              <ChevronUpIcon class-name="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              :disabled="index === local.length - 1 || orderMutation.isPending.value"
              :title="'下移'"
              :aria-label="`将「${category.name}」下移`"
              class="flex h-8 w-8 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
              @click="move(index, 1)"
            >
              <ChevronDownIcon class-name="h-3.5 w-3.5" />
            </button>
          </div>

          <div class="min-w-0 flex-1">
            <template v-if="editingId === category.id">
              <input
                v-focus
                v-model="editDraft"
                :aria-label="`重命名「${category.name}」`"
                class="w-full rounded border border-slate-300 px-2 py-1 text-[13px] text-slate-800 outline-none focus:border-slate-500"
                @input="editError = null"
                @blur="commitRename(category)"
                @keydown.enter="commitRename(category)"
                @keydown.esc="
                  editDraft = category.name;
                  editError = null;
                  editingId = null;
                "
              />
              <p class="mt-0.5 text-[11px] text-red-600">{{ editError ?? '' }}</p>
            </template>
            <template v-else>
              <p class="truncate text-[13px] text-slate-800">{{ category.name }}</p>
              <p class="text-[11px] text-slate-400">{{ category.media_count }} 个素材</p>
            </template>
          </div>

          <button
            type="button"
            :disabled="busy || editingId === category.id"
            title="重命名"
            :aria-label="`重命名「${category.name}」`"
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
            @click="startRename(category)"
          >
            <PencilIcon class-name="h-4 w-4" />
          </button>
          <button
            type="button"
            :disabled="busy"
            title="删除分类"
            :aria-label="`删除「${category.name}」`"
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-30"
            @click="confirmDelete(category)"
          >
            <TrashIcon class-name="h-4 w-4" />
          </button>
        </div>
      </div>

      <div class="shrink-0 border-t border-slate-100 px-4 py-2.5 sm:px-5">
        <p class="text-[11px] text-slate-400">
          删除分类不会删除素材：其中的素材会回到「未分类」。用 ↑ ↓ 调整显示顺序。
        </p>
      </div>
    </div>
  </div>
</template>
