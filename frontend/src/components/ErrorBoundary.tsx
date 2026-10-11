/** 全局错误边界（M5 打磨）。
 *
 * 任何页面组件抛错都不会再让整站白屏：兜底显示可读信息 + 「重新加载」按钮，
 * 同时把错误打到控制台，方便排查。
 */

import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 保留完整信息在控制台，便于进一步定位
    console.error('[FayeLong] 页面渲染出错：', error, info.componentStack)
  }

  private reload = () => {
    window.location.reload()
  }

  private dismiss = () => {
    this.setState({ error: null })
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="mx-auto max-w-2xl px-6 py-16">
        <div className="rounded-xl border border-red-100 bg-red-50/60 p-6">
          <h2 className="text-[16px] font-medium text-red-700">页面出错了</h2>
          <p className="mt-2 text-[13px] leading-relaxed text-red-600">
            当前界面遇到一个未预期的问题，你的学习数据（音频、笔记、生词、听写记录）都保存在本地，
            不会因此丢失。
          </p>
          <pre className="mt-3 max-h-40 overflow-auto rounded-lg bg-white/70 px-3 py-2 text-[12px] text-slate-600">
            {error.message || String(error)}
          </pre>
          <div className="mt-4 flex items-center gap-2">
            <button
              type="button"
              onClick={this.reload}
              className="rounded-lg bg-slate-900 px-3.5 py-2 text-[13px] text-white transition-colors hover:bg-slate-700"
            >
              重新加载页面
            </button>
            <button
              type="button"
              onClick={this.dismiss}
              className="rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-[13px] text-slate-600 transition-colors hover:bg-slate-50"
            >
              尝试忽略并继续
            </button>
          </div>
        </div>
      </div>
    )
  }
}
