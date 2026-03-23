from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape as html_escape
from html import unescape as html_unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ALLOWED_BITRATES = {64, 96, 128, 160, 192, 256, 320}
ALLOWED_SAMPLE_RATES = {8000, 12000, 16000, 22050, 24000, 32000, 44100, 48000}
ALLOWED_CHANNELS = {1, 2}
ALLOWED_RETENTION_MINUTES = {5, 10, 30, 60}
DEFAULT_RETENTION_MINUTES = 10


@dataclass(frozen=True)
class ConversionFamily:
    key: str
    label: str
    accept: str
    supported_outputs: dict[str, str]
    extensions: tuple[str, ...] = ()
    supports_bitrate: bool = False
    supports_sample_rate: bool = False
    supports_channels: bool = False
    default_format: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "accept": self.accept,
            "extensions": list(self.extensions),
            "default_format": self.default_format,
            "supports": {
                "bitrate": self.supports_bitrate,
                "sample_rate": self.supports_sample_rate,
                "channels": self.supports_channels,
            },
            "formats": [
                {"value": fmt, "label": fmt, "mime_type": mime}
                for fmt, mime in self.supported_outputs.items()
            ],
        }


AUDIO_OUTPUTS = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
    "opus": "audio/opus",
}

VIDEO_OUTPUTS = {
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mkv": "video/x-matroska",
    "mov": "video/quicktime",
    "avi": "video/x-msvideo",
}

IMAGE_OUTPUTS = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "gif": "image/gif",
    "tif": "image/tiff",
    "tiff": "image/tiff",
}

DOCUMENT_OUTPUTS = {
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "html": "text/html; charset=utf-8",
}

FAMILIES = {
    "audio": ConversionFamily(
        key="audio",
        label="音频",
        accept="audio/",
        supported_outputs=AUDIO_OUTPUTS,
        extensions=("wav", "mp3", "ogg", "flac", "m4a", "aac", "opus"),
        supports_bitrate=True,
        supports_sample_rate=True,
        supports_channels=True,
        default_format="mp3",
    ),
    "video": ConversionFamily(
        key="video",
        label="视频",
        accept="video/",
        supported_outputs=VIDEO_OUTPUTS,
        extensions=("mp4", "webm", "mkv", "mov", "avi", "m4v", "ts", "mts", "m2ts"),
        supports_bitrate=True,
        supports_sample_rate=False,
        supports_channels=False,
        default_format="mp4",
    ),
    "image": ConversionFamily(
        key="image",
        label="图片",
        accept="image/",
        supported_outputs=IMAGE_OUTPUTS,
        extensions=("png", "jpg", "jpeg", "webp", "bmp", "gif", "tif", "tiff"),
        default_format="png",
    ),
    "document": ConversionFamily(
        key="document",
        label="文档",
        accept="text/",
        supported_outputs=DOCUMENT_OUTPUTS,
        extensions=("txt", "md", "markdown", "html", "htm"),
        default_format="md",
    ),
}

DEFAULT_FAMILY = "audio"


def list_capabilities() -> dict[str, Any]:
    return {
        "default_family": DEFAULT_FAMILY,
        "bitrates": sorted(ALLOWED_BITRATES),
        "sample_rates": sorted(ALLOWED_SAMPLE_RATES),
        "channels": sorted(ALLOWED_CHANNELS),
        "retention_minutes": sorted(ALLOWED_RETENTION_MINUTES),
        "default_retention_minutes": DEFAULT_RETENTION_MINUTES,
        "families": [family.to_public_dict() for family in FAMILIES.values()],
    }


def get_family(key: str | None) -> ConversionFamily | None:
    if not key:
        return FAMILIES.get(DEFAULT_FAMILY)
    return FAMILIES.get(key.lower())


def infer_family_from_content_type(content_type: str | None) -> ConversionFamily | None:
    if not content_type:
        return FAMILIES.get(DEFAULT_FAMILY)
    if content_type.startswith("audio/"):
        return FAMILIES["audio"]
    if content_type.startswith("video/"):
        return FAMILIES["video"]
    if content_type.startswith("image/"):
        return FAMILIES["image"]
    if content_type.startswith("text/") or content_type in {"application/xhtml+xml", "application/xml"}:
        return FAMILIES["document"]
    return None


def infer_family_from_filename(filename: str | None) -> ConversionFamily | None:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    if not suffix:
        return None
    for family in FAMILIES.values():
        if suffix in family.extensions:
            return family
    return None


def parse_option(value, allowed_values, field_name):
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"无效的{field_name}") from exc
    if parsed not in allowed_values:
        raise ValueError(f"不支持的{field_name}: {parsed}")
    return parsed


def normalize_format(family: ConversionFamily, fmt: str | None) -> str:
    candidate = (fmt or "").strip().lower()
    if not candidate:
        return family.default_format
    if candidate not in family.supported_outputs:
        raise ValueError(f"不支持的输出格式: {candidate}")
    return candidate


def output_media_type(family_key: str, fmt: str) -> str:
    family = get_family(family_key)
    if not family:
        return "application/octet-stream"
    return family.supported_outputs.get(fmt, "application/octet-stream")


def build_download_filename(original_name: str | None, fmt: str) -> str:
    return f"{Path(original_name or 'output').stem}.{fmt}"


def build_ffmpeg_command(
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    family_key: str,
    fmt: str,
    bitrate_kbps: int | None = None,
    sample_rate: int | None = None,
    channels: int | None = None,
) -> list[str]:
    family = get_family(family_key)
    if not family:
        raise ValueError(f"未知的转换类型: {family_key}")

    cmd = [ffmpeg_path, "-y", "-i", str(input_path)]

    if family.key == "audio":
        if sample_rate:
            cmd += ["-ar", str(sample_rate)]
        if channels:
            cmd += ["-ac", str(channels)]
        if bitrate_kbps and fmt in {"mp3", "ogg", "m4a", "aac", "opus"}:
            cmd += ["-b:a", f"{bitrate_kbps}k"]

        codec_map = {
            "wav": ["-c:a", "pcm_s16le"],
            "mp3": ["-c:a", "libmp3lame"],
            "ogg": ["-c:a", "libvorbis"],
            "flac": ["-c:a", "flac"],
            "m4a": ["-c:a", "aac"],
            "aac": ["-c:a", "aac"],
            "opus": ["-c:a", "libopus"],
        }
        return cmd + codec_map[fmt] + [str(output_path)]

    if family.key == "video":
        if fmt in {"mp4", "mov", "mkv"}:
            if bitrate_kbps:
                cmd += ["-b:v", f"{bitrate_kbps}k"]
            else:
                cmd += ["-crf", "23"]
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac"]
            if fmt in {"mp4", "mov"}:
                cmd += ["-movflags", "+faststart"]
        elif fmt == "webm":
            if bitrate_kbps:
                cmd += ["-b:v", f"{bitrate_kbps}k"]
            else:
                cmd += ["-crf", "32"]
            cmd += ["-c:v", "libvpx-vp9", "-c:a", "libopus"]
        elif fmt == "avi":
            if bitrate_kbps:
                cmd += ["-b:v", f"{bitrate_kbps}k"]
            else:
                cmd += ["-q:v", "5"]
            cmd += ["-c:v", "mpeg4", "-c:a", "libmp3lame"]
        else:
            raise ValueError(f"不支持的输出格式: {fmt}")

        return cmd + [str(output_path)]

    raise ValueError(f"未知的转换类型: {family.key}")


def convert_image_file(input_path: Path, output_path: Path, fmt: str):
    try:
        from PIL import Image, ImageColor, ImageOps
    except ImportError as exc:
        raise ValueError("图片转换依赖 Pillow，请先安装依赖") from exc

    fmt = fmt.lower()
    save_format = "JPEG" if fmt in {"jpg", "jpeg"} else fmt.upper()

    with Image.open(input_path) as original:
        image = ImageOps.exif_transpose(original)

        if fmt in {"jpg", "jpeg"}:
            if image.mode in {"RGBA", "LA"} or ("transparency" in image.info):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, ImageColor.getrgb("white"))
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
        elif image.mode not in {"RGB", "RGBA", "L", "LA", "P"}:
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")

        image.save(output_path, format=save_format)


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "cp936"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _detect_document_source(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix in {"txt"}:
        return "txt"
    if suffix in {"md", "markdown"}:
        return "md"
    if suffix in {"html", "htm"}:
        return "html"
    return "txt"


def _markdown_inline_to_html(text: str) -> str:
    escaped = html_escape(text)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)
    return escaped


def _markdown_to_html(markdown_text: str) -> str:
    lines = _normalize_text(markdown_text).split("\n")
    parts: list[str] = []
    paragraph: list[str] = []
    code_lines: list[str] = []
    in_code = False
    list_type: str | None = None

    def flush_paragraph():
        nonlocal paragraph
        if paragraph:
            content = " ".join(line.strip() for line in paragraph).strip()
            if content:
                parts.append(f"<p>{_markdown_inline_to_html(content)}</p>")
            paragraph = []

    def close_list():
        nonlocal list_type
        if list_type == "ul":
            parts.append("</ul>")
        elif list_type == "ol":
            parts.append("</ol>")
        list_type = None

    for line in lines:
        stripped = line.strip()
        if in_code:
            if stripped.startswith("```"):
                code_text = "\n".join(code_lines)
                parts.append(f"<pre><code>{html_escape(code_text)}</code></pre>")
                code_lines = []
                in_code = False
            else:
                code_lines.append(line)
            continue

        if stripped.startswith("```"):
            flush_paragraph()
            close_list()
            in_code = True
            code_lines = []
            continue

        if not stripped:
            flush_paragraph()
            close_list()
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            parts.append(f"<h{level}>{_markdown_inline_to_html(heading.group(2).strip())}</h{level}>")
            continue

        bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
        ordered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if bullet or ordered:
            flush_paragraph()
            if bullet:
                if list_type != "ul":
                    close_list()
                    parts.append("<ul>")
                    list_type = "ul"
                parts.append(f"<li>{_markdown_inline_to_html(bullet.group(1).strip())}</li>")
            else:
                if list_type != "ol":
                    close_list()
                    parts.append("<ol>")
                    list_type = "ol"
                parts.append(f"<li>{_markdown_inline_to_html(ordered.group(1).strip())}</li>")
            continue

        paragraph.append(stripped)

    flush_paragraph()
    close_list()
    if in_code:
        code_text = "\n".join(code_lines)
        parts.append(f"<pre><code>{html_escape(code_text)}</code></pre>")

    body = "\n".join(parts)
    return f"<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\" /></head><body>{body}</body></html>"


class _HTMLToTextParser(HTMLParser):
    BLOCK_TAGS = {"p", "div", "section", "article", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self, mode: str = "text"):
        super().__init__(convert_charrefs=True)
        self.mode = mode
        self.parts: list[str] = []
        self.list_stack: list[dict[str, Any]] = []
        self.in_pre = False
        self.in_script = False
        self.link_stack: list[str] = []

    def _append(self, text: str):
        self.parts.append(text)

    def _ensure_blank_line(self):
        if not self.parts:
            return
        text = "".join(self.parts)
        if not text.endswith("\n\n"):
            if text.endswith("\n"):
                self._append("\n")
            else:
                self._append("\n\n")

    def _ensure_line_break(self):
        if not self.parts:
            return
        if not "".join(self.parts).endswith("\n"):
            self._append("\n")

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr_map = dict(attrs)
        if tag in {"script", "style"}:
            self.in_script = True
            return
        if tag in self.BLOCK_TAGS:
            if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
                self._ensure_blank_line()
                if self.mode == "markdown":
                    self._append("#" * int(tag[1]) + " ")
            else:
                self._ensure_blank_line()
        elif tag == "br":
            self._ensure_line_break()
        elif tag in {"strong", "b"}:
            self._append("**" if self.mode == "markdown" else "")
        elif tag in {"em", "i"}:
            self._append("*" if self.mode == "markdown" else "")
        elif tag == "code" and not self.in_pre:
            self._append("`" if self.mode == "markdown" else "")
        elif tag == "pre":
            self._ensure_blank_line()
            self.in_pre = True
            if self.mode == "markdown":
                self._append("```\n")
        elif tag == "ul":
            self._ensure_blank_line()
            self.list_stack.append({"type": "ul", "index": 0})
        elif tag == "ol":
            self._ensure_blank_line()
            self.list_stack.append({"type": "ol", "index": 1})
        elif tag == "li":
            self._ensure_line_break()
            if self.list_stack:
                top = self.list_stack[-1]
                if top["type"] == "ol":
                    self._append(f"{top['index']}. " if self.mode == "markdown" else "")
                    top["index"] += 1
                else:
                    self._append("- " if self.mode == "markdown" else "")
            else:
                self._append("- " if self.mode == "markdown" else "")
        elif tag == "a":
            href = attr_map.get("href", "")
            self.link_stack.append(href)
            if self.mode == "markdown":
                self._append("[")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style"}:
            self.in_script = False
            return
        if tag in {"strong", "b"} and self.mode == "markdown":
            self._append("**")
        elif tag in {"em", "i"} and self.mode == "markdown":
            self._append("*")
        elif tag == "code" and not self.in_pre and self.mode == "markdown":
            self._append("`")
        elif tag == "pre":
            if self.mode == "markdown":
                self._append("\n```")
            self.in_pre = False
            self._ensure_blank_line()
        elif tag == "a":
            href = self.link_stack.pop() if self.link_stack else ""
            if self.mode == "markdown" and href:
                self._append(f"]({href})")
        elif tag == "li":
            self._ensure_line_break()
        elif tag in self.BLOCK_TAGS or tag in {"ul", "ol"}:
            self._ensure_blank_line()

    def handle_data(self, data):
        if self.in_script:
            return
        if self.in_pre:
            self._append(data)
            return
        text = html_unescape(data)
        text = re.sub(r"\s+", " ", text)
        if text:
            self._append(text)

    def get_output(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _html_to_text(html_text: str) -> str:
    parser = _HTMLToTextParser(mode="text")
    parser.feed(html_text)
    parser.close()
    return parser.get_output()


def _html_to_markdown(html_text: str) -> str:
    parser = _HTMLToTextParser(mode="markdown")
    parser.feed(html_text)
    parser.close()
    return parser.get_output()


def _text_to_html(text: str) -> str:
    normalized = _normalize_text(text).strip()
    if not normalized:
        body = "<p></p>"
    else:
        paragraphs = re.split(r"\n\s*\n", normalized)
        body_parts = []
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            body_parts.append(f"<p>{html_escape(paragraph).replace(chr(10), '<br />')}</p>")
        body = "\n".join(body_parts) or "<p></p>"
    return f"<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\" /></head><body>{body}</body></html>"


def _text_to_markdown(text: str) -> str:
    return _normalize_text(text).strip()


def _markdown_to_text(markdown_text: str) -> str:
    html_text = _markdown_to_html(markdown_text)
    return _html_to_text(html_text)


def _html_to_source_text(html_text: str) -> str:
    return _html_to_text(html_text)


def convert_document_file(input_path: Path, output_path: Path, fmt: str):
    source = _detect_document_source(input_path)
    content = _read_text_file(input_path)
    fmt = fmt.lower()

    if source == "txt":
        if fmt == "txt":
            result = _text_to_markdown(content)
        elif fmt == "md":
            result = _text_to_markdown(content)
        elif fmt == "html":
            result = _text_to_html(content)
        else:
            raise ValueError(f"不支持的输出格式: {fmt}")
    elif source == "md":
        if fmt == "txt":
            result = _markdown_to_text(content)
        elif fmt == "md":
            result = _text_to_markdown(content)
        elif fmt == "html":
            result = _markdown_to_html(content)
        else:
            raise ValueError(f"不支持的输出格式: {fmt}")
    elif source == "html":
        if fmt == "txt":
            result = _html_to_source_text(content)
        elif fmt == "md":
            result = _html_to_markdown(content)
        elif fmt == "html":
            result = content
        else:
            raise ValueError(f"不支持的输出格式: {fmt}")
    else:
        if fmt == "html":
            result = _text_to_html(content)
        elif fmt == "md":
            result = _text_to_markdown(content)
        elif fmt == "txt":
            result = _text_to_markdown(content)
        else:
            raise ValueError(f"不支持的输出格式: {fmt}")

    output_path.write_text(result, encoding="utf-8")
