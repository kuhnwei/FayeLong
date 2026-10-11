"""文件响应工具：支持 HTTP Range 的流式响应。

浏览器的 <audio controls> 在拖动进度条 / 续播时会发送 `Range: bytes=...` 请求，
服务端必须返回 `206 Partial Content` + `Content-Range`，否则无法定位播放位置。
"""

from __future__ import annotations

import logging
import mimetypes
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import Response, StreamingResponse

logger = logging.getLogger(__name__)

CHUNK_SIZE = 256 * 1024
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")

_MIME_OVERRIDES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".wma": "audio/x-ms-wma",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
}


def guess_mime(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in _MIME_OVERRIDES:
        return _MIME_OVERRIDES[suffix]
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def _iter_file(path: Path, start: int, end: int):
    remaining = end - start + 1
    with open(path, "rb") as fh:
        fh.seek(start)
        while remaining > 0:
            chunk = fh.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _unsatisfiable(size: int) -> Response:
    return Response(
        status_code=416,
        headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"},
    )


def file_response(
    path: str | Path,
    request: Request,
    content_type: str | None = None,
    filename: str | None = None,
    download: bool = False,
) -> Response:
    """返回支持 Range 的文件响应（音频/视频播放、切片下载都用它）。"""
    path = Path(path)
    size = path.stat().st_size
    mime = content_type or guess_mime(path)

    headers: dict[str, str] = {"Accept-Ranges": "bytes", "Cache-Control": "no-store"}
    if filename:
        inline = "attachment" if download else "inline"
        headers["Content-Disposition"] = f"{inline}; filename*=UTF-8''{quote(filename)}"

    range_header = (request.headers.get("range") or "").strip()
    if not range_header:
        return StreamingResponse(
            _iter_file(path, 0, size - 1),
            media_type=mime,
            headers={**headers, "Content-Length": str(size)},
        )

    match = _RANGE_RE.match(range_header)
    if not match:
        return _unsatisfiable(size)

    raw_start, raw_end = match.group(1), match.group(2)
    if raw_start == "":
        # bytes=-N 表示最后 N 字节
        if raw_end == "" or int(raw_end) == 0:
            return _unsatisfiable(size)
        tail = int(raw_end)
        start, end = max(0, size - tail), size - 1
    else:
        start = int(raw_start)
        end = int(raw_end) if raw_end else size - 1

    end = min(end, size - 1)
    if start > end or start >= size:
        return _unsatisfiable(size)

    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(end - start + 1)
    return StreamingResponse(
        _iter_file(path, start, end),
        status_code=206,
        media_type=mime,
        headers=headers,
    )
