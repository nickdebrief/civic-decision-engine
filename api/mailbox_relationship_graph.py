from __future__ import annotations

import re
from dataclasses import dataclass
from email.utils import getaddresses
from typing import Any

from api.document_intake import is_mailbox_document


REFERENCE_RE = re.compile(
    r"\b(?:CASE|REF|MBOX|DOC|TRM|TRM-ATT|CDE|CREF)-[A-Za-z0-9][A-Za-z0-9_.:-]*\b",
    re.IGNORECASE,
)
MESSAGE_ID_RE = re.compile(r"<[^<>\s]+@[^<>\s]+>")


NODE_STYLE = {
    "Email": ("mail", "communication"),
    "Person": ("user", "participant"),
    "Institution": ("building", "institution"),
    "Case": ("folder", "case"),
    "Reference Number": ("hash", "reference"),
    "Attachment": ("paperclip", "attachment"),
    "Intake Record": ("archive", "intake"),
}

EDGE_WEIGHTS = {
    "Sent By": 2,
    "Sent To": 1,
    "CC": 1,
    "Replies To": 6,
    "References": 4,
    "Attached To": 3,
    "Belongs To Case": 4,
    "Created Intake": 5,
    "Mentions Reference": 2,
    "Related Communication": 1,
}


@dataclass(frozen=True)
class MailboxGraphFilters:
    document: str | None = None
    institution: str | None = None
    person: str | None = None
    case: str | None = None
    reference: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    status: str | None = None
    offset: int = 0
    limit: int = 1000


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _key(value: Any) -> str:
    return _clean(value).casefold()


def _slug(value: Any) -> str:
    cleaned = _key(value)
    cleaned = re.sub(r"[^a-z0-9@._:-]+", "-", cleaned).strip("-")
    return cleaned or "unknown"


def _node_id(node_type: str, label: str) -> str:
    return f"{node_type.casefold().replace(' ', '_')}:{_slug(label)}"


def _message_node_id(document: dict[str, Any], message: dict[str, Any]) -> str:
    document_id = _clean(document.get("document_identifier") or document.get("intake_id"))
    index = _clean(message.get("message_index"))
    return f"email:{_slug(document_id)}:{index or '0'}"


def _participant_label(raw: Any) -> list[str]:
    value = _clean(raw)
    if not value:
        return []
    labels: list[str] = []
    for name, address in getaddresses([value]):
        name = _clean(name)
        address = _clean(address)
        if name and address:
            labels.append(f"{name} <{address}>")
        elif address:
            labels.append(address)
        elif name:
            labels.append(name)
    if not labels:
        labels.append(value)
    seen: set[str] = set()
    unique: list[str] = []
    for label in labels:
        key = _key(label)
        if key not in seen:
            seen.add(key)
            unique.append(label)
    return unique


def _message_date(message: dict[str, Any]) -> str:
    return _clean(message.get("date_header_parsed") or message.get("date_header_raw"))


def _date_matches(message: dict[str, Any], filters: MailboxGraphFilters) -> bool:
    value = _message_date(message)
    if filters.date_from and value and value[:10] < filters.date_from:
        return False
    if filters.date_to and value and value[:10] > filters.date_to:
        return False
    return True


def _document_case_labels(document: dict[str, Any], message: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for key in (
        "case",
        "case_id",
        "case_name",
        "case_reference",
        "case_reference_identifier",
        "canonical_case",
    ):
        value = _clean(document.get(key))
        if value:
            labels.append(value)
    for value in (
        document.get("reference_identifier"),
        document.get("title"),
        document.get("description"),
        document.get("category"),
        message.get("subject_decoded"),
        message.get("plain_text_preview"),
    ):
        for match in REFERENCE_RE.findall(_clean(value)):
            if match.upper().startswith("CASE-"):
                labels.append(match)
    return _unique_sorted(labels)


def _reference_labels(document: dict[str, Any], message: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("reference_identifier", "document_identifier"):
        values.append(_clean(document.get(key)))
    for key in ("message_id", "in_reply_to"):
        values.append(_clean(message.get(key)))
    references = message.get("references") or []
    if isinstance(references, str):
        values.extend(references.split())
    elif isinstance(references, list):
        values.extend(_clean(item) for item in references)
    for key in ("subject_decoded", "plain_text_preview", "sanitized_html_preview"):
        values.extend(REFERENCE_RE.findall(_clean(message.get(key))))
    return _unique_sorted(value for value in values if value)


def _unique_sorted(values: Any) -> list[str]:
    seen: dict[str, str] = {}
    for value in values:
        label = _clean(value)
        if label:
            seen.setdefault(_key(label), label)
    return [seen[key] for key in sorted(seen)]


def _add_node(nodes: dict[str, dict[str, Any]], node_id: str, node_type: str, label: str, metadata: dict[str, Any] | None = None) -> None:
    if node_id in nodes:
        existing = nodes[node_id].setdefault("metadata", {})
        for key, value in (metadata or {}).items():
            if value not in (None, "", []):
                existing.setdefault(key, value)
        return
    icon, colour = NODE_STYLE[node_type]
    nodes[node_id] = {
        "id": node_id,
        "type": node_type,
        "label": label,
        "metadata": metadata or {},
        "icon": icon,
        "colour_category": colour,
    }


def _add_edge(
    edges: dict[tuple[str, str, str], dict[str, Any]],
    source: str,
    target: str,
    relationship_type: str,
    *,
    weight: int | None = None,
    evidence: dict[str, Any] | None = None,
) -> None:
    if source == target:
        return
    key = (source, target, relationship_type)
    if key not in edges:
        edges[key] = {
            "source": source,
            "target": target,
            "relationship_type": relationship_type,
            "weight": 0,
            "evidence_metadata": {},
        }
    edge = edges[key]
    edge["weight"] = int(edge["weight"]) + int(weight or EDGE_WEIGHTS.get(relationship_type, 1))
    evidence_map = edge.setdefault("evidence_metadata", {})
    for name, value in (evidence or {}).items():
        if value in (None, "", []):
            continue
        if name not in evidence_map:
            evidence_map[name] = value
            continue
        if evidence_map[name] == value:
            continue
        if not isinstance(evidence_map[name], list):
            evidence_map[name] = [evidence_map[name]]
        if value not in evidence_map[name]:
            evidence_map[name].append(value)


def _message_matches(document: dict[str, Any], message: dict[str, Any], filters: MailboxGraphFilters) -> bool:
    if filters.document:
        document_values = {
            _key(document.get("intake_id")),
            _key(document.get("document_identifier")),
        }
        if _key(filters.document) not in document_values:
            return False
    if filters.institution and _key(filters.institution) not in _key(document.get("institution_source")):
        return False
    if filters.status and _key(filters.status) not in {
        _key(message.get("parse_status")),
        _key(document.get("status")),
        _key(document.get("visibility")),
    }:
        return False
    if not _date_matches(message, filters):
        return False
    if filters.person:
        people = []
        for key in ("from_raw", "sender_raw", "reply_to_raw", "to_raw", "cc_raw"):
            people.extend(_participant_label(message.get(key)))
        if not any(_key(filters.person) in _key(person) for person in people):
            return False
    if filters.case:
        if not any(_key(filters.case) in _key(label) for label in _document_case_labels(document, message)):
            return False
    if filters.reference:
        if not any(_key(filters.reference) in _key(label) for label in _reference_labels(document, message)):
            return False
    return True


def _message_subject(message: dict[str, Any]) -> str:
    return _clean(message.get("subject_decoded")) or f"Message {message.get('message_index') or ''}".strip()


def _attachment_label(attachment: dict[str, Any], index: int) -> str:
    return _clean(
        attachment.get("filename")
        or attachment.get("long_filename")
        or attachment.get("content_id")
        or f"Attachment {index}"
    )


def build_mailbox_relationship_graph(
    documents: list[dict[str, Any]],
    *,
    filters: MailboxGraphFilters | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Build a deterministic relationship graph from existing MBOX projections."""
    filters = filters or MailboxGraphFilters()
    bounded_limit = min(max(int(filters.limit or 1000), 1), 5000)
    offset = max(int(filters.offset or 0), 0)

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    messages_seen = 0
    messages_added = 0
    message_id_to_node: dict[str, str] = {}
    reference_to_emails: dict[str, list[str]] = {}
    case_to_emails: dict[str, list[str]] = {}
    institution_to_emails: dict[str, list[str]] = {}
    attachment_to_emails: dict[str, list[str]] = {}

    mailbox_documents = sorted(
        (document for document in documents if is_mailbox_document(document)),
        key=lambda item: (_clean(item.get("publication_date")), _clean(item.get("document_identifier")), _clean(item.get("intake_id"))),
    )
    for document in mailbox_documents:
        metadata = document.get("email_metadata") or {}
        messages = [message for message in metadata.get("messages") or [] if isinstance(message, dict)]
        messages.sort(key=lambda message: int(message.get("message_index") or 0))
        intake_label = _clean(document.get("document_identifier") or document.get("title") or document.get("intake_id"))
        intake_node = _node_id("Intake Record", intake_label)
        institution_label = _clean(document.get("institution_source"))
        institution_node = _node_id("Institution", institution_label) if institution_label else ""

        for message in messages:
            if not _message_matches(document, message, filters):
                continue
            messages_seen += 1
            if messages_seen <= offset:
                continue
            if messages_added >= bounded_limit:
                break
            messages_added += 1

            email_node = _message_node_id(document, message)
            message_id = _clean(message.get("message_id"))
            _add_node(
                nodes,
                email_node,
                "Email",
                _message_subject(message),
                {
                    "document_identifier": document.get("document_identifier"),
                    "document_id": document.get("intake_id"),
                    "message_index": message.get("message_index"),
                    "message_id": message_id,
                    "date": _message_date(message),
                    "parse_status": message.get("parse_status"),
                    "byte_start": message.get("byte_start"),
                    "byte_end": message.get("byte_end"),
                    "message_digest": message.get("message_digest"),
                    "url": f"/documents/{document.get('intake_id')}?message={message.get('message_index')}",
                },
            )
            _add_node(nodes, intake_node, "Intake Record", intake_label, {"document_id": document.get("intake_id")})
            _add_edge(edges, intake_node, email_node, "Created Intake", evidence={"document_identifier": document.get("document_identifier")})
            if message_id:
                message_id_to_node[_key(message_id)] = email_node

            if institution_label:
                _add_node(nodes, institution_node, "Institution", institution_label, {"source": "document.institution_source"})
                _add_edge(edges, email_node, institution_node, "Related Communication", weight=2, evidence={"field": "institution_source"})
                institution_to_emails.setdefault(_key(institution_label), []).append(email_node)

            for relation, field in (("Sent By", "from_raw"), ("Sent By", "sender_raw"), ("Sent To", "to_raw"), ("CC", "cc_raw")):
                for person in _participant_label(message.get(field)):
                    person_node = _node_id("Person", person)
                    _add_node(nodes, person_node, "Person", person, {"field": field})
                    _add_edge(edges, email_node, person_node, relation, evidence={"message_index": message.get("message_index")})

            for case_label in _document_case_labels(document, message):
                case_node = _node_id("Case", case_label)
                _add_node(nodes, case_node, "Case", case_label, {"source": "document_or_message_reference"})
                _add_edge(edges, email_node, case_node, "Belongs To Case", evidence={"message_index": message.get("message_index")})
                case_to_emails.setdefault(_key(case_label), []).append(email_node)

            for reference in _reference_labels(document, message):
                reference_node = _node_id("Reference Number", reference)
                _add_node(nodes, reference_node, "Reference Number", reference, {"source": "message_or_document_reference"})
                relationship = "References" if reference in {message_id, _clean(message.get("in_reply_to"))} or reference in (message.get("references") or []) else "Mentions Reference"
                _add_edge(edges, email_node, reference_node, relationship, evidence={"message_index": message.get("message_index")})
                reference_to_emails.setdefault(_key(reference), []).append(email_node)

            for index, attachment in enumerate(message.get("attachments_metadata") or [], start=1):
                if not isinstance(attachment, dict):
                    continue
                attachment_label = _attachment_label(attachment, index)
                attachment_key = _key(attachment.get("content_id") or attachment_label)
                attachment_node = _node_id("Attachment", attachment_key)
                _add_node(
                    nodes,
                    attachment_node,
                    "Attachment",
                    attachment_label,
                    {
                        "media_type": attachment.get("media_type"),
                        "byte_size": attachment.get("byte_size"),
                        "content_id": attachment.get("content_id"),
                    },
                )
                _add_edge(edges, attachment_node, email_node, "Attached To", evidence={"message_index": message.get("message_index")})
                attachment_to_emails.setdefault(attachment_key, []).append(email_node)

        if messages_added >= bounded_limit:
            break

    for edge_source in nodes:
        node = nodes[edge_source]
        if node.get("type") != "Email":
            continue
        message_id = _key(node.get("metadata", {}).get("message_id"))
        if not message_id:
            continue
        # Reply edges are added after all messages are known so referenced targets
        # can point to an Email node rather than only a Reference Number node.
    for document in mailbox_documents:
        for message in document.get("email_metadata", {}).get("messages") or []:
            source = _message_node_id(document, message)
            if source not in nodes:
                continue
            for reference in [_clean(message.get("in_reply_to")), *(_unique_sorted(message.get("references") or []))]:
                target = message_id_to_node.get(_key(reference))
                if target and target in nodes:
                    _add_edge(edges, source, target, "Replies To", evidence={"reference": reference})

    for relation_map, relation_type in (
        (case_to_emails, "Belongs To Case"),
        (institution_to_emails, "Related Communication"),
        (reference_to_emails, "References"),
        (attachment_to_emails, "Attached To"),
    ):
        for evidence_key, email_nodes in relation_map.items():
            unique_nodes = _unique_sorted(email_nodes)
            if len(unique_nodes) < 2:
                continue
            for index, source in enumerate(unique_nodes):
                for target in unique_nodes[index + 1 : min(index + 4, len(unique_nodes))]:
                    if source in nodes and target in nodes:
                        _add_edge(edges, source, target, relation_type, weight=1, evidence={"shared": evidence_key})

    return {
        "nodes": sorted(nodes.values(), key=lambda node: (_clean(node.get("type")), _clean(node.get("label")).casefold(), _clean(node.get("id")))),
        "edges": sorted(edges.values(), key=lambda edge: (_clean(edge.get("source")), _clean(edge.get("target")), _clean(edge.get("relationship_type")))),
    }
