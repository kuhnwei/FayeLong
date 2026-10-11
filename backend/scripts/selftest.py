"""环境自检脚本：ffmpeg / 数据库 / 语音识别 / 在线翻译。

用法（在 backend 目录下）：
    .venv\\Scripts\\python.exe scripts\\selftest.py          # 快速自检
    .venv\\Scripts\\python.exe scripts\\selftest.py --asr    # 额外做一次真实识别（较慢）

对应 FR-D4「启动时自检并给出清晰中文提示」。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import DB_PATH, INBOX_DIR  # noqa: E402
from app.core.paths import audio_wav_path, clips_dir, media_dir  # noqa: E402
from app.core.tools import ffmpeg_path, ffprobe_path  # noqa: E402
from app.db import init_db  # noqa: E402
from app.services import asr as asr_service  # noqa: E402
from app.services import dict as dict_service  # noqa: E402
from app.services import dictation  # noqa: E402
from app.services.translate import translate  # noqa: E402

SEP = "=" * 60


def check_tools(ok: bool) -> bool:
    print("【媒体工具】")
    for name, path in (("ffmpeg", ffmpeg_path()), ("ffprobe", ffprobe_path())):
        print(f"  {name:8s} {'OK  ' + path if path else '缺失 —— 转码/切片不可用'}")
        if not path:
            ok = False
    return ok


def check_asr(ok: bool, deep: bool) -> bool:
    print("\n【语音识别】")
    info = asr_service.status()
    if not info["installed"]:
        print("  faster-whisper 未安装 —— 执行 pip install -r backend/requirements-ml.txt")
        return False
    print(f"  faster-whisper OK（模型规格 {info['model']}）")
    if info["ready"]:
        print(f"  模型已就绪 {info['dir']}")
    else:
        print(f"  模型未就绪（首次识别时自动从 {info['endpoint']} 下载）")

    if not deep:
        return ok

    sample = next(
        (p for p in sorted(INBOX_DIR.glob("*"))
         if p.is_file() and p.suffix.lower() in (".wav", ".mp3", ".m4a")),
        None,
    )
    if sample is None:
        print("  （收件箱中没有可用于测试的音频，跳过真实识别）")
        return ok

    print(f"  真实识别测试：{sample.name} …")
    try:
        sentences, meta = asr_service.transcribe(sample)
    except Exception as exc:  # noqa: BLE001
        print(f"  识别失败：{exc}")
        return False
    print(f"    -> {len(sentences)} 句 / 语言 {meta['language']}（置信度 {meta['language_probability']:.2f}）")
    for item in sentences[:3]:
        print(f"       [{item.start_ms:>6}-{item.end_ms:>6}ms] {item.text[:70]}")
    return ok


def check_translate(ok: bool) -> bool:
    print("\n【在线翻译】")
    sample = "I received a letter this morning and it made me very happy."
    print(f"  原文：{sample}")
    result = translate(sample)
    if result["text"]:
        print(f"  译文：{result['text']}   （引擎 {result['engine']}"
              f"{'，命中缓存' if result['cached'] else ''}）")
    else:
        print("  失败：所有在线引擎均不可用（网络受限？）")
        ok = False
    return ok


def check_dict(ok: bool) -> bool:
    """词典与词形还原自检（离线可跑）。"""
    print("\n【词典（ECDICT）】")
    info = dict_service.status()
    if not info["installed"]:
        print("  词库未安装 —— 执行 backend/scripts/fetch_dict.py 安装后可用")
        print("  （查词浮层会退化为「仅跳转牛津 / 朗文」）")
        return ok
    print(f"  词库就绪 {info['path']}")
    print(f"  词条数 {info['entries']}，体积 {info['size_bytes'] / 1024 / 1024:.1f} MB")

    cases = [
        ("hello", "基础词"),
        ("received", "变形 → 原型（exchange）"),
        ("running", "ing 还原"),
        ("studies", "复数 / 三单还原"),
        ("children", "不规则复数"),
    ]
    for word, label in cases:
        result = dict_service.lookup(word)
        if result.found and result.entry is not None:
            first = result.entry.translation[0] if result.entry.translation else ""
            arrow = f"→ {result.entry.word}（{result.via}）" if result.lemma else ""
            print(f"  OK   {word:10s} {label:22s} {arrow} {first[:36]}")
        else:
            print(f"  未收录 {word:10s} {label}")
            ok = False
    return ok


def check_dictation(ok: bool) -> bool:
    """听写校验算法自检（纯函数，离线可跑）。"""
    print("\n【听写校验】")
    expected = "I received a letter this morning."
    cases = [
        ("I received a letter this morning.", 100.0, True, "完全正确"),
        ("i received a letter this morning", 100.0, True, "忽略大小写与标点"),
        ("I recieved a letter this morning", 83.3, False, "拼错一个词"),
        ("I received a letter", 66.7, False, "漏掉两个词"),
        ("I received a letter this morning today", 100.0, False, "多写一个词（不算完全正确）"),
    ]
    for text, want_acc, want_ok, label in cases:
        result = dictation.evaluate(expected, text)
        hit = abs(result["accuracy"] - want_acc) < 0.05 and result["is_correct"] is want_ok
        mark = "OK  " if hit else "不符"
        print(f"  {mark} {label:22s} 正确率 {result['accuracy']:5.1f}% "
              f"（对 {result['correct']} 错 {result['wrong']} "
              f"漏 {result['missing']} 多 {result['extra']}）")
        if not hit:
            ok = False
    return ok


def check_routes(ok: bool) -> bool:
    """接口完整性自检（M5）：确认关键路由都在，避免重构时误删。"""
    print("\n【接口完整性】")
    from app.main import app  # noqa: PLC0415  （延迟导入，避免拖慢其它检查）

    paths = app.openapi().get("paths", {})
    expected = [
        "/api/media",
        "/api/media/{media_id}/stream",
        "/api/media/{media_id}/progress",
        "/api/media/{media_id}/notes",
        "/api/media/{media_id}/notes/export",
        "/api/sentences/{sentence_id}",
        "/api/attempts",
        "/api/dict/{word}",
        "/api/vocab",
        "/api/vocab/export",
        "/api/notes/{sentence_id}",
        "/api/stats",
    ]
    missing = [p for p in expected if p not in paths]
    print(f"  路由总数 {len(paths)}，关键路由 {len(expected) - len(missing)}/{len(expected)}")
    for path in missing:
        print(f"  缺失 {path}")
    if missing:
        ok = False
    return ok


def main() -> int:
    deep = "--asr" in sys.argv

    print(SEP)
    print("FayeLong 环境自检")
    print(SEP)

    ok = check_tools(True)

    init_db()
    print(f"\n【数据目录】\n  数据库 {DB_PATH}")
    print(f"  收件箱 {INBOX_DIR}")
    print(f"  媒体库 {media_dir(0).parent}")
    print(f"  切片   {clips_dir(0)}")
    print(f"  标准音频示例路径 {audio_wav_path(0)}")

    ok = check_asr(ok, deep)
    ok = check_translate(ok)
    ok = check_dict(ok)
    ok = check_dictation(ok)
    ok = check_routes(ok)

    print("\n" + SEP)
    print("结论：" + ("全部通过 ✔" if ok else "存在未通过项 ✘"))
    print(SEP)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
