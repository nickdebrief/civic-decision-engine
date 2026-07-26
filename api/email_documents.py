from __future__ import annotations

import html
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from email import policy
from email.header import decode_header
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any


MAX_EML_BYTES = 25 * 1024 * 1024
MAX_HEADER_COUNT = 200
MAX_HEADER_LENGTH = 8192
MAX_MIME_DEPTH = 12
MAX_MIME_PARTS = 200
MAX_ATTACHMENT_COUNT = 100
MAX_DECODED_BODY_BYTES = 2 * 1024 * 1024
MAX_DECODED_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_TOTAL_DECODED_BYTES = 50 * 1024 * 1024
MAX_SEARCH_TEXT_CHARS = 200_000
MAX_HTML_RENDER_CHARS = 100_000
MAX_MSG_BYTES = 25 * 1024 * 1024
MAX_MSG_DIRECTORY_ENTRIES = 1024
MAX_MSG_STREAM_COUNT = 768
MAX_MSG_PROPERTY_COUNT = 512
MAX_MSG_PROPERTY_SIZE = 2 * 1024 * 1024
MAX_MSG_RECIPIENT_COUNT = 200
MAX_MSG_ATTACHMENT_COUNT = 100
MAX_MSG_EMBEDDED_DEPTH = 1
MAX_MSG_BODY_BYTES = 2 * 1024 * 1024
MAX_MSG_HTML_BYTES = 1 * 1024 * 1024
MAX_MSG_RTF_COMPRESSED_BYTES = 4 * 1024 * 1024
MAX_MSG_RTF_DECODED_BYTES = 8 * 1024 * 1024
MAX_MSG_DECODED_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_MSG_TOTAL_DECODED_BYTES = 50 * 1024 * 1024
MAX_MSG_RENDERED_OUTPUT_CHARS = 100_000

CFB_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD
DIFSECT = 0xFFFFFFFC

EMAIL_GOVERNANCE_BOUNDARY = (
    "Parsed email metadata reflects fields contained in the preserved source "
    "message. It does not independently verify sender identity, delivery, "
    "receipt, authorship, authenticity, factual accuracy, legal status, "
    "evidential sufficiency, or external validation."
)
OUTLOOK_GOVERNANCE_BOUNDARY = (
    "Parsed Outlook metadata reflects fields contained in the preserved source "
    "message. It does not independently verify sender identity, delivery, "
    "receipt, authorship, authenticity, factual accuracy, legal status, "
    "evidential sufficiency, or external validation."
)

_HEADER_SEPARATOR_RE = re.compile(br"\r\n\r\n|\n\n|\r\r")
_SCRIPT_STYLE_RE = re.compile(
    r"<\s*(script|style|iframe|form|object|embed|meta|link)\b.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_VOID_ACTIVE_RE = re.compile(
    r"<\s*(script|style|iframe|form|object|embed|meta|link|base|frame|frameset)\b[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
_REMOTE_IMAGE_RE = re.compile(r"<\s*img\b[^>]*>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


class _EmailSanitizer(HTMLParser):
    allowed_tags = {
        "a",
        "abbr",
        "b",
        "blockquote",
        "br",
        "code",
        "dd",
        "div",
        "dl",
        "dt",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "li",
        "ol",
        "p",
        "pre",
        "span",
        "strong",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "ul",
    }
    allowed_attrs = {"href", "title", "colspan", "rowspan", "scope"}
    blocked_schemes = ("javascript:", "data:", "vbscript:", "file:", "ftp:")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._blocked_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "iframe", "form", "object", "embed"}:
            self._blocked_depth += 1
            return
        if self._blocked_depth:
            return
        if tag not in self.allowed_tags:
            return
        safe_attrs: list[str] = []
        for name, value in attrs:
            name = name.lower()
            value = "" if value is None else str(value)
            if name.startswith("on") or name not in self.allowed_attrs:
                continue
            if name == "href":
                normalized = value.strip().casefold()
                if normalized.startswith(self.blocked_schemes):
                    continue
                if normalized.startswith(("http://", "https://", "//")):
                    continue
            safe_attrs.append(f'{name}="{html.escape(value, quote=True)}"')
        suffix = f" {' '.join(safe_attrs)}" if safe_attrs else ""
        self.parts.append(f"<{tag}{suffix}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "iframe", "form", "object", "embed"}:
            self._blocked_depth = max(0, self._blocked_depth - 1)
            return
        if self._blocked_depth:
            return
        if tag in self.allowed_tags and tag != "br":
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._blocked_depth:
            return
        self.parts.append(html.escape(data))

    def handle_entityref(self, name: str) -> None:
        if not self._blocked_depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._blocked_depth:
            self.parts.append(f"&#{name};")

    def sanitized(self) -> str:
        return "".join(self.parts)[:MAX_HTML_RENDER_CHARS]


def _header_separator_present(data: bytes) -> bool:
    return bool(_HEADER_SEPARATOR_RE.search(data[: min(len(data), 512 * 1024)]))


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    fragments: list[str] = []
    for fragment, charset in decode_header(value):
        if isinstance(fragment, bytes):
            encoding = charset or "utf-8"
            try:
                fragments.append(fragment.decode(encoding, errors="replace"))
            except LookupError:
                fragments.append(fragment.decode("utf-8", errors="replace"))
        else:
            fragments.append(fragment)
    return "".join(fragments).strip()


def _addresses(value: str | None) -> list[str]:
    decoded = _decode_header_value(value)
    results = []
    for name, address in getaddresses([decoded]):
        display = " ".join(part for part in (name.strip(), f"<{address.strip()}>" if address.strip() else "") if part)
        if display:
            results.append(display)
    return results


def _parsed_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except Exception:
        return None


def _payload_bytes(part: Any) -> bytes:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        if isinstance(raw, str):
            charset = part.get_content_charset() or "utf-8"
            return raw.encode(charset, errors="replace")
        return b""
    return bytes(payload)


def _decode_text_part(part: Any, *, max_bytes: int = MAX_DECODED_BODY_BYTES) -> str:
    data = _payload_bytes(part)
    if len(data) > max_bytes:
        raise ValueError("document_intake_email_decoded_body_too_large")
    charset = part.get_content_charset() or "utf-8"
    try:
        return data.decode(charset, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def sanitize_email_html(value: str) -> str:
    stripped = _SCRIPT_STYLE_RE.sub("", value or "")
    stripped = _VOID_ACTIVE_RE.sub("", stripped)
    stripped = _REMOTE_IMAGE_RE.sub("[remote image suppressed]", stripped)
    parser = _EmailSanitizer()
    parser.feed(stripped[:MAX_HTML_RENDER_CHARS])
    parser.close()
    return parser.sanitized()


def html_to_text(value: str) -> str:
    text = _SCRIPT_STYLE_RE.sub(" ", value or "")
    text = _VOID_ACTIVE_RE.sub(" ", text)
    text = _REMOTE_IMAGE_RE.sub(" remote image suppressed ", text)
    text = _TAG_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", html.unescape(text)).strip()


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def _filetime(value: bytes) -> str | None:
    if len(value) < 8:
        return None
    raw = _u64(value, 0)
    if not raw:
        return None
    try:
        epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
        return (epoch + timedelta(microseconds=raw / 10)).isoformat().replace("+00:00", "Z")
    except (OverflowError, ValueError):
        return None


def _decode_msg_text(value: bytes, property_type: str | None = None) -> str:
    data = bytes(value or b"")[:MAX_MSG_PROPERTY_SIZE]
    if property_type == "001F" or (property_type is None and b"\x00" in data[: min(len(data), 32)]):
        try:
            return data.decode("utf-16-le", errors="replace").rstrip("\x00").strip()
        except UnicodeDecodeError:
            pass
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding, errors="replace").rstrip("\x00").strip()
        except LookupError:
            continue
    return ""


def _decode_msg_int(value: bytes) -> int | None:
    if len(value) < 4:
        return None
    return struct.unpack_from("<i", value, 0)[0]


@dataclass(frozen=True)
class _CFBEntry:
    name: str
    object_type: int
    left: int
    right: int
    child: int
    start_sector: int
    stream_size: int
    index: int
    path: tuple[str, ...] = ()


@dataclass(frozen=True)
class _CFBStream:
    name: str
    path: tuple[str, ...]
    data: bytes


class _CompoundFile:
    def __init__(self, data: bytes) -> None:
        if not data:
            raise ValueError("document_intake_file_required")
        if len(data) > MAX_MSG_BYTES:
            raise ValueError("document_intake_file_too_large")
        if len(data) < 512 or not data.startswith(CFB_SIGNATURE):
            raise ValueError("document_intake_invalid_msg")
        self.data = data
        sector_shift = _u16(data, 30)
        mini_sector_shift = _u16(data, 32)
        if sector_shift not in {9, 12} or mini_sector_shift != 6:
            raise ValueError("document_intake_invalid_msg")
        self.sector_size = 1 << sector_shift
        self.mini_sector_size = 1 << mini_sector_shift
        self.num_fat_sectors = _u32(data, 44)
        self.first_directory_sector = _u32(data, 48)
        self.mini_stream_cutoff = _u32(data, 56) or 4096
        self.first_mini_fat_sector = _u32(data, 60)
        self.num_mini_fat_sectors = _u32(data, 64)
        self.first_difat_sector = _u32(data, 68)
        self.num_difat_sectors = _u32(data, 72)
        self.fat = self._read_fat()
        self.entries = self._read_directory()
        self._assign_paths()
        self.root = next((entry for entry in self.entries if entry.object_type == 5), None)
        self.mini_fat = self._read_mini_fat()
        self.mini_stream = (
            self._read_regular_stream(self.root.start_sector, self.root.stream_size)
            if self.root and self.root.stream_size
            else b""
        )

    def _sector(self, sector_id: int) -> bytes:
        if sector_id < 0 or sector_id >= (len(self.data) - 512) // self.sector_size:
            raise ValueError("document_intake_msg_corrupt_directory")
        offset = 512 + sector_id * self.sector_size
        return self.data[offset : offset + self.sector_size]

    def _sector_chain(self, start_sector: int, *, max_entries: int) -> list[int]:
        if start_sector in {FREESECT, ENDOFCHAIN}:
            return []
        chain: list[int] = []
        seen: set[int] = set()
        sector = start_sector
        while sector not in {FREESECT, ENDOFCHAIN}:
            if sector in seen:
                raise ValueError("document_intake_msg_cyclic_stream")
            if sector >= len(self.fat) or len(chain) >= max_entries:
                raise ValueError("document_intake_msg_stream_limit_exceeded")
            seen.add(sector)
            chain.append(sector)
            sector = self.fat[sector]
        return chain

    def _read_fat(self) -> list[int]:
        difat = [_u32(self.data, offset) for offset in range(76, 512, 4)]
        next_difat = self.first_difat_sector
        for _ in range(min(self.num_difat_sectors, 64)):
            if next_difat in {FREESECT, ENDOFCHAIN}:
                break
            sector = self._sector(next_difat)
            entries_per_difat = self.sector_size // 4 - 1
            difat.extend(_u32(sector, index * 4) for index in range(entries_per_difat))
            next_difat = _u32(sector, entries_per_difat * 4)
        fat_sectors = [sector for sector in difat if sector not in {FREESECT, ENDOFCHAIN, FATSECT, DIFSECT}]
        if self.num_fat_sectors and len(fat_sectors) < self.num_fat_sectors:
            raise ValueError("document_intake_msg_corrupt_directory")
        fat: list[int] = []
        for sector_id in fat_sectors[: self.num_fat_sectors or len(fat_sectors)]:
            sector = self._sector(sector_id)
            fat.extend(_u32(sector, index) for index in range(0, self.sector_size, 4))
        if not fat:
            raise ValueError("document_intake_msg_corrupt_directory")
        return fat

    def _read_regular_stream(self, start_sector: int, size: int) -> bytes:
        if size > MAX_MSG_TOTAL_DECODED_BYTES:
            raise ValueError("document_intake_msg_decoded_content_too_large")
        # Stream count and stream length are separate boundaries. Native Outlook
        # messages can store a single body, HTML, RTF, or attachment stream across
        # more sectors than the total-stream-count limit, while the declared byte
        # size remains bounded by the caller-specific parser limits.
        chain = self._sector_chain(
            start_sector,
            max_entries=max(1, size // self.sector_size + 2),
        )
        return b"".join(self._sector(sector) for sector in chain)[:size]

    def _read_mini_fat(self) -> list[int]:
        if self.first_mini_fat_sector in {FREESECT, ENDOFCHAIN} or not self.num_mini_fat_sectors:
            return []
        data = b"".join(
            self._sector(sector)
            for sector in self._sector_chain(self.first_mini_fat_sector, max_entries=self.num_mini_fat_sectors + 1)
        )
        return [_u32(data, index) for index in range(0, len(data), 4)]

    def _read_mini_stream(self, start_sector: int, size: int) -> bytes:
        if not self.mini_fat or not self.mini_stream:
            return self._read_regular_stream(start_sector, size)
        chain: list[int] = []
        seen: set[int] = set()
        sector = start_sector
        while sector not in {FREESECT, ENDOFCHAIN}:
            if sector in seen or sector >= len(self.mini_fat) or len(chain) > MAX_MSG_STREAM_COUNT:
                raise ValueError("document_intake_msg_cyclic_stream")
            seen.add(sector)
            chain.append(sector)
            sector = self.mini_fat[sector]
        chunks = []
        for mini_sector in chain:
            offset = mini_sector * self.mini_sector_size
            chunks.append(self.mini_stream[offset : offset + self.mini_sector_size])
        return b"".join(chunks)[:size]

    def _read_directory(self) -> list[_CFBEntry]:
        directory = self._read_regular_stream(
            self.first_directory_sector,
            MAX_MSG_DIRECTORY_ENTRIES * 128,
        )
        entries: list[_CFBEntry] = []
        for index in range(0, len(directory), 128):
            raw = directory[index : index + 128]
            if len(raw) < 128:
                break
            name_length = _u16(raw, 64)
            if name_length < 2 or name_length > 64:
                name = ""
            else:
                name = raw[: name_length - 2].decode("utf-16-le", errors="replace")
            object_type = raw[66]
            if object_type == 0 and not name:
                continue
            entries.append(
                _CFBEntry(
                    name=name,
                    object_type=object_type,
                    left=_u32(raw, 68),
                    right=_u32(raw, 72),
                    child=_u32(raw, 76),
                    start_sector=_u32(raw, 116),
                    stream_size=_u64(raw, 120),
                    index=index // 128,
                )
            )
            if len(entries) > MAX_MSG_DIRECTORY_ENTRIES:
                raise ValueError("document_intake_msg_directory_limit_exceeded")
        if not entries:
            raise ValueError("document_intake_invalid_msg")
        return entries

    def _collect_tree(self, index: int, seen: set[int] | None = None) -> list[int]:
        if index in {FREESECT, ENDOFCHAIN} or index >= len(self.entries):
            return []
        seen = seen or set()
        if index in seen:
            raise ValueError("document_intake_msg_corrupt_directory")
        seen.add(index)
        entry = self.entries[index]
        return self._collect_tree(entry.left, seen) + [index] + self._collect_tree(entry.right, seen)

    def _assign_paths(self) -> None:
        entries = list(self.entries)

        def descend(parent_index: int, parent_path: tuple[str, ...]) -> None:
            if parent_index >= len(entries):
                return
            parent = entries[parent_index]
            for child_index in self._collect_tree(parent.child):
                child = entries[child_index]
                path = parent_path + (() if child.object_type == 2 else (child.name,))
                entries[child_index] = _CFBEntry(
                    child.name,
                    child.object_type,
                    child.left,
                    child.right,
                    child.child,
                    child.start_sector,
                    child.stream_size,
                    child.index,
                    path,
                )
                if child.object_type in {1, 5}:
                    descend(child_index, path)

        root_index = next((entry.index for entry in entries if entry.object_type == 5), 0)
        entries[root_index] = _CFBEntry(
            entries[root_index].name,
            entries[root_index].object_type,
            entries[root_index].left,
            entries[root_index].right,
            entries[root_index].child,
            entries[root_index].start_sector,
            entries[root_index].stream_size,
            entries[root_index].index,
            (),
        )
        descend(root_index, ())
        self.entries = entries

    def streams(self) -> list[_CFBStream]:
        streams = []
        for entry in self.entries:
            if entry.object_type != 2:
                continue
            if entry.stream_size > MAX_MSG_PROPERTY_SIZE and not entry.name.startswith("__substg1.0_3701"):
                raise ValueError("document_intake_msg_property_too_large")
            data = (
                self._read_mini_stream(entry.start_sector, entry.stream_size)
                if entry.stream_size < self.mini_stream_cutoff
                else self._read_regular_stream(entry.start_sector, entry.stream_size)
            )
            streams.append(_CFBStream(entry.name, entry.path, data))
            if len(streams) > MAX_MSG_STREAM_COUNT:
                raise ValueError("document_intake_msg_stream_limit_exceeded")
        return streams


_SUBSTG_RE = re.compile(r"^__substg1\.0_([0-9A-Fa-f]{4})([0-9A-Fa-f]{4})$")


def _msg_property_streams(streams: list[_CFBStream]) -> dict[tuple[str, ...], dict[str, tuple[str, bytes]]]:
    grouped: dict[tuple[str, ...], dict[str, tuple[str, bytes]]] = {}
    property_count = 0
    for stream in streams:
        match = _SUBSTG_RE.match(stream.name)
        if not match:
            continue
        property_count += 1
        if property_count > MAX_MSG_PROPERTY_COUNT:
            raise ValueError("document_intake_msg_property_limit_exceeded")
        tag, property_type = match.groups()
        grouped.setdefault(stream.path, {})[tag.upper()] = (property_type.upper(), stream.data)
    return grouped


def _msg_text(properties: dict[str, tuple[str, bytes]], tag: str) -> str:
    value = properties.get(tag)
    if not value:
        return ""
    property_type, data = value
    return _decode_msg_text(data, property_type)


def _msg_binary(properties: dict[str, tuple[str, bytes]], tag: str) -> bytes:
    value = properties.get(tag)
    return value[1] if value else b""


def _msg_time(properties: dict[str, tuple[str, bytes]], tag: str) -> str | None:
    value = properties.get(tag)
    return _filetime(value[1]) if value else None


def _msg_int(properties: dict[str, tuple[str, bytes]], tag: str) -> int | None:
    value = properties.get(tag)
    return _decode_msg_int(value[1]) if value else None


def _msg_address(name: str, email_address: str, smtp_address: str = "") -> str:
    address = smtp_address or email_address
    if name and address:
        return f"{name} <{address}>"
    return name or address


def parse_outlook_msg_metadata(data: bytes) -> dict[str, Any]:
    cfb = _CompoundFile(data)
    streams = cfb.streams()
    grouped = _msg_property_streams(streams)
    root_properties = grouped.get((), {})
    if "__properties_version1.0" not in {stream.name for stream in streams} and not (
        {"001A", "0037", "0C1A", "1000", "1013"} & set(root_properties)
    ):
        raise ValueError("document_intake_invalid_msg")

    subject = _msg_text(root_properties, "0037")
    plain_text = _msg_text(root_properties, "1000")
    if len(plain_text.encode("utf-8")) > MAX_MSG_BODY_BYTES:
        raise ValueError("document_intake_msg_body_too_large")
    html_bytes = _msg_binary(root_properties, "1013")
    if len(html_bytes) > MAX_MSG_HTML_BYTES:
        raise ValueError("document_intake_msg_body_too_large")
    raw_html = _decode_msg_text(html_bytes, None) if html_bytes else ""
    sanitized_html = sanitize_email_html(raw_html)[:MAX_MSG_RENDERED_OUTPUT_CHARS] if raw_html else ""
    html_text = html_to_text(raw_html) if raw_html else ""
    rtf_body = _msg_binary(root_properties, "1009")
    if len(rtf_body) > MAX_MSG_RTF_COMPRESSED_BYTES:
        raise ValueError("document_intake_msg_rtf_too_large")

    recipient_groups = [
        (path, properties)
        for path, properties in grouped.items()
        if any(part.startswith("__recip_version1.0_") for part in path)
    ]
    if len(recipient_groups) > MAX_MSG_RECIPIENT_COUNT:
        raise ValueError("document_intake_msg_too_many_recipients")
    to_addresses: list[str] = []
    cc_addresses: list[str] = []
    bcc_addresses: list[str] = []
    reply_to = _msg_text(root_properties, "1046") or _msg_text(root_properties, "0C17")
    for _path, properties in sorted(recipient_groups, key=lambda pair: pair[0]):
        display_name = _msg_text(properties, "3001")
        email_address = _msg_text(properties, "3003")
        smtp_address = _msg_text(properties, "39FE")
        recipient = _msg_address(display_name, email_address, smtp_address)
        recipient_type = _msg_int(properties, "0C15") or 1
        if not recipient:
            continue
        if recipient_type == 2:
            cc_addresses.append(recipient)
        elif recipient_type == 3:
            bcc_addresses.append(recipient)
        else:
            to_addresses.append(recipient)

    attachment_groups = [
        (path, properties)
        for path, properties in grouped.items()
        if any(part.startswith("__attach_version1.0_") for part in path)
    ]
    if len(attachment_groups) > MAX_MSG_ATTACHMENT_COUNT:
        raise ValueError("document_intake_msg_too_many_attachments")
    attachments: list[dict[str, Any]] = []
    embedded_message_count = 0
    total_attachment_bytes = 0
    for index, (path, properties) in enumerate(sorted(attachment_groups, key=lambda pair: pair[0]), start=1):
        data_stream = _msg_binary(properties, "3701")
        total_attachment_bytes += len(data_stream)
        if len(data_stream) > MAX_MSG_DECODED_ATTACHMENT_BYTES or total_attachment_bytes > MAX_MSG_TOTAL_DECODED_BYTES:
            raise ValueError("document_intake_msg_attachment_too_large")
        filename = _msg_text(properties, "3704")
        long_filename = _msg_text(properties, "3707")
        attach_method = _msg_int(properties, "3705")
        is_embedded_message = attach_method == 5 or any("__substg1.0_3701000D" == stream.name for stream in streams if stream.path == path)
        if is_embedded_message:
            embedded_message_count += 1
            if embedded_message_count > MAX_MSG_EMBEDDED_DEPTH:
                raise ValueError("document_intake_msg_embedded_message_too_deep")
        attachments.append(
            {
                "attachment_index": index,
                "filename": long_filename or filename or f"attachment-{index}",
                "long_filename": long_filename,
                "filename_generated": not bool(long_filename or filename),
                "media_type": _msg_text(properties, "370E") or "application/octet-stream",
                "byte_size": len(data_stream),
                "content_disposition": "attachment",
                "content_id": _msg_text(properties, "3712"),
                "attachment_method": attach_method,
                "mime_tag": _msg_text(properties, "370E"),
                "is_attached_message": is_embedded_message,
                "is_embedded_message": is_embedded_message,
            }
        )

    body_search = _WHITESPACE_RE.sub(" ", " ".join(part for part in (plain_text, html_text) if part)).strip()
    sender_name = _msg_text(root_properties, "0C1A")
    sender_email = _msg_text(root_properties, "0C1F")
    sender_smtp = _msg_text(root_properties, "5D01")
    sent_rep_name = _msg_text(root_properties, "0042")
    sent_rep_email = _msg_text(root_properties, "0065")
    internet_message_id = _msg_text(root_properties, "1035")

    return {
        "source_format": "outlook_msg",
        "source_format_label": "Microsoft Outlook Message",
        "message_class": _msg_text(root_properties, "001A"),
        "message_id": internet_message_id,
        "internet_message_id": internet_message_id,
        "date_header_raw": _msg_time(root_properties, "0039") or "",
        "date_header_parsed": _msg_time(root_properties, "0039"),
        "subject_raw": subject,
        "subject_decoded": subject,
        "sender_name": sender_name,
        "sender_email": sender_email,
        "sender_raw": _msg_address(sender_name, sender_email, sender_smtp),
        "sender_smtp_address": sender_smtp,
        "sent_representing_name": sent_rep_name,
        "sent_representing_email": sent_rep_email,
        "from_raw": _msg_address(sender_name, sender_email, sender_smtp),
        "from_addresses": [_msg_address(sender_name, sender_email, sender_smtp)] if _msg_address(sender_name, sender_email, sender_smtp) else [],
        "to_raw": " · ".join(to_addresses),
        "to_addresses": to_addresses,
        "cc_raw": " · ".join(cc_addresses),
        "cc_addresses": cc_addresses,
        "bcc_raw": " · ".join(bcc_addresses),
        "reply_to_raw": reply_to,
        "reply_to": reply_to,
        "in_reply_to": _msg_text(root_properties, "1042"),
        "references": [token for token in _msg_text(root_properties, "1039").split() if token],
        "conversation_topic": _msg_text(root_properties, "0070"),
        "conversation_index": _msg_binary(root_properties, "0071").hex(),
        "conversation_id": _msg_text(root_properties, "3013"),
        "client_submit_time": _msg_time(root_properties, "0039"),
        "delivery_time": _msg_time(root_properties, "0E06"),
        "creation_time": _msg_time(root_properties, "3007"),
        "last_modification_time": _msg_time(root_properties, "3008"),
        "mime_version": "",
        "content_type": _msg_text(root_properties, "001A") or "application/vnd.ms-outlook",
        "content_transfer_encoding": "",
        "is_multipart": False,
        "plain_text_body": plain_text,
        "sanitized_html_body": sanitized_html,
        "rtf_body_present": bool(rtf_body),
        "body_search_text": body_search[:MAX_SEARCH_TEXT_CHARS],
        "attachments_metadata": attachments,
        "attachment_count": len(attachments),
        "embedded_message_count": embedded_message_count,
        "parser_warnings": [],
        "parser_defects": [],
    }


def validate_outlook_msg_document(data: bytes) -> dict[str, Any]:
    return parse_outlook_msg_metadata(data)


def _walk_message(message: Any, *, depth: int = 0) -> list[Any]:
    if depth > MAX_MIME_DEPTH:
        raise ValueError("document_intake_email_mime_too_deep")
    parts = [message]
    if message.is_multipart():
        for child in message.iter_parts():
            parts.extend(_walk_message(child, depth=depth + 1))
            if len(parts) > MAX_MIME_PARTS:
                raise ValueError("document_intake_email_too_many_parts")
    return parts


def parse_email_metadata(data: bytes) -> dict[str, Any]:
    if not data:
        raise ValueError("document_intake_file_required")
    if len(data) > MAX_EML_BYTES:
        raise ValueError("document_intake_file_too_large")
    if not _header_separator_present(data):
        raise ValueError("document_intake_invalid_email")

    try:
        message = BytesParser(policy=policy.default).parsebytes(data)
    except Exception as exc:
        raise ValueError("document_intake_invalid_email") from exc

    header_items = list(message.raw_items())
    if not header_items:
        raise ValueError("document_intake_invalid_email")
    if len(header_items) > MAX_HEADER_COUNT:
        raise ValueError("document_intake_email_too_many_headers")
    if any(len(str(name)) + len(str(value)) > MAX_HEADER_LENGTH for name, value in header_items):
        raise ValueError("document_intake_email_header_too_large")

    header_names = {name.lower() for name, _value in header_items}
    if not ({"from", "to", "subject", "date", "message-id", "mime-version", "content-type"} & header_names):
        raise ValueError("document_intake_invalid_email")

    parts = _walk_message(message)
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict[str, Any]] = []
    total_decoded = 0
    warnings: list[str] = []

    for part in parts:
        defects = [defect.__class__.__name__ for defect in getattr(part, "defects", [])]
        warnings.extend(defects)
        if part.is_multipart():
            continue
        payload = _payload_bytes(part)
        total_decoded += len(payload)
        if total_decoded > MAX_TOTAL_DECODED_BYTES:
            raise ValueError("document_intake_email_decoded_content_too_large")
        disposition = str(part.get_content_disposition() or "").lower()
        content_type = str(part.get_content_type() or "application/octet-stream")
        filename = part.get_filename()
        decoded_filename = _decode_header_value(filename) if filename else ""
        is_attached_message = content_type == "message/rfc822"
        is_attachment = disposition == "attachment" or bool(decoded_filename) or is_attached_message
        if is_attachment:
            if len(attachments) >= MAX_ATTACHMENT_COUNT:
                raise ValueError("document_intake_email_too_many_attachments")
            if len(payload) > MAX_DECODED_ATTACHMENT_BYTES:
                raise ValueError("document_intake_email_attachment_too_large")
            generated = not bool(decoded_filename)
            attachments.append(
                {
                    "filename": decoded_filename or f"attachment-{len(attachments) + 1}",
                    "filename_generated": generated,
                    "media_type": content_type,
                    "byte_size": len(payload),
                    "content_disposition": disposition or "inline",
                    "content_id": str(part.get("Content-ID") or "").strip(),
                    "is_attached_message": is_attached_message,
                }
            )
            continue
        if content_type == "text/plain":
            plain_parts.append(_decode_text_part(part))
        elif content_type == "text/html":
            html_parts.append(_decode_text_part(part))

    subject_raw = str(message.get("Subject") or "")
    plain_text = "\n\n".join(part.strip() for part in plain_parts if part.strip())
    raw_html = "\n\n".join(part.strip() for part in html_parts if part.strip())
    sanitized_html = sanitize_email_html(raw_html) if raw_html else ""
    html_text = html_to_text(raw_html) if raw_html else ""
    body_search = _WHITESPACE_RE.sub(" ", " ".join(part for part in (plain_text, html_text) if part)).strip()

    return {
        "source_format": "rfc5322_eml",
        "source_format_label": "RFC 5322 Email",
        "message_id": str(message.get("Message-ID") or "").strip(),
        "date_header_raw": str(message.get("Date") or "").strip(),
        "date_header_parsed": _parsed_date(str(message.get("Date") or "")),
        "from_raw": str(message.get("From") or "").strip(),
        "from_addresses": _addresses(str(message.get("From") or "")),
        "sender_raw": str(message.get("Sender") or "").strip(),
        "reply_to_raw": str(message.get("Reply-To") or "").strip(),
        "to_raw": str(message.get("To") or "").strip(),
        "to_addresses": _addresses(str(message.get("To") or "")),
        "cc_raw": str(message.get("Cc") or "").strip(),
        "cc_addresses": _addresses(str(message.get("Cc") or "")),
        "bcc_raw": str(message.get("Bcc") or "").strip(),
        "subject_raw": subject_raw,
        "subject_decoded": _decode_header_value(subject_raw),
        "in_reply_to": str(message.get("In-Reply-To") or "").strip(),
        "references": [token for token in str(message.get("References") or "").split() if token],
        "mime_version": str(message.get("MIME-Version") or "").strip(),
        "content_type": str(message.get_content_type() or "").strip(),
        "content_transfer_encoding": str(message.get("Content-Transfer-Encoding") or "").strip(),
        "is_multipart": bool(message.is_multipart()),
        "plain_text_body": plain_text[:MAX_DECODED_BODY_BYTES],
        "sanitized_html_body": sanitized_html[:MAX_HTML_RENDER_CHARS],
        "body_search_text": body_search[:MAX_SEARCH_TEXT_CHARS],
        "attachments_metadata": attachments,
        "attachment_count": len(attachments),
        "parser_warnings": sorted(set(warnings)),
    }


def validate_email_document(data: bytes) -> dict[str, Any]:
    return parse_email_metadata(data)


def email_projection_search_values(metadata: dict[str, Any]) -> list[Any]:
    email_metadata = metadata.get("email_metadata")
    if not isinstance(email_metadata, dict):
        return []
    values: list[Any] = [
        email_metadata.get("message_id"),
        email_metadata.get("internet_message_id"),
        email_metadata.get("date_header_raw"),
        email_metadata.get("from_raw"),
        email_metadata.get("from_addresses"),
        email_metadata.get("sender_raw"),
        email_metadata.get("sender_name"),
        email_metadata.get("sender_email"),
        email_metadata.get("sender_smtp_address"),
        email_metadata.get("sent_representing_name"),
        email_metadata.get("sent_representing_email"),
        email_metadata.get("reply_to_raw"),
        email_metadata.get("reply_to"),
        email_metadata.get("to_raw"),
        email_metadata.get("to_addresses"),
        email_metadata.get("cc_raw"),
        email_metadata.get("cc_addresses"),
        email_metadata.get("subject_raw"),
        email_metadata.get("subject_decoded"),
        email_metadata.get("in_reply_to"),
        email_metadata.get("references"),
        email_metadata.get("conversation_topic"),
        email_metadata.get("conversation_id"),
        email_metadata.get("message_class"),
        email_metadata.get("mime_version"),
        email_metadata.get("content_type"),
        email_metadata.get("source_format_label"),
        email_metadata.get("body_search_text"),
    ]
    for attachment in email_metadata.get("attachments_metadata") or []:
        if isinstance(attachment, dict):
            values.extend(
                [
                    attachment.get("filename"),
                    attachment.get("media_type"),
                    attachment.get("content_disposition"),
                    attachment.get("content_id"),
                ]
            )
    return values
