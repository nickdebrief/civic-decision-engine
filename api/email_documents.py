from __future__ import annotations

import html
import re
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

EMAIL_GOVERNANCE_BOUNDARY = (
    "Parsed email metadata reflects fields contained in the preserved source "
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
        email_metadata.get("date_header_raw"),
        email_metadata.get("from_raw"),
        email_metadata.get("from_addresses"),
        email_metadata.get("sender_raw"),
        email_metadata.get("reply_to_raw"),
        email_metadata.get("to_raw"),
        email_metadata.get("to_addresses"),
        email_metadata.get("cc_raw"),
        email_metadata.get("cc_addresses"),
        email_metadata.get("subject_raw"),
        email_metadata.get("subject_decoded"),
        email_metadata.get("in_reply_to"),
        email_metadata.get("references"),
        email_metadata.get("mime_version"),
        email_metadata.get("content_type"),
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
