"""Controller-owned Stage 77 custody-evidence registry primitives.

This module deliberately accepts evidence-set identifiers, never client paths.
The registrar reads fixed retained bytes, constructs the canonical authority, and
records immutable rows before an envelope can rely on the registration.
"""
from __future__ import annotations

import hashlib, json, os, sqlite3, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "cde-stage77-custody-evidence-registry-v1"
PURPOSE = "post_correction_generation"
ROLES = ("database_capture", "database_digest", "checkpoint_wal_shm", "custody_points_1_5", "archive_export", "receipt", "recovery_verification", "runtime_authority", "artifact_inventory")

def _reject_duplicates(pairs):
    d = {}
    for k, v in pairs:
        if k in d: raise ValueError("stage77_custody_evidence_duplicate_key")
        d[k] = v
    return d

def canonical(value: Any) -> bytes:
    def check(v: Any) -> None:
        if v is None or isinstance(v, float): raise ValueError("stage77_custody_evidence_canonical_invalid")
        if isinstance(v, str) and unicodedata.normalize("NFC", v) != v: raise ValueError("stage77_custody_evidence_canonical_invalid")
        if isinstance(v, dict):
            for k, x in v.items():
                if not isinstance(k, str): raise ValueError("stage77_custody_evidence_canonical_invalid")
                check(k); check(x)
        elif isinstance(v, list):
            for x in v: check(x)
        elif not isinstance(v, (str, bool, int)): raise ValueError("stage77_custody_evidence_canonical_invalid")
    check(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def strict_json(text: str) -> dict[str, Any]:
    value = json.loads(text, object_pairs_hook=_reject_duplicates)
    if not isinstance(value, dict) or canonical(value).decode() != text: raise ValueError("stage77_custody_evidence_noncanonical")
    return value

def digest(payload: Mapping[str, Any]) -> str:
    p = dict(payload); p.pop("payload_digest", None)
    return hashlib.sha256(canonical(p)).hexdigest()


def _sha256(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("stage77_custody_evidence_digest_invalid")
    return value


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 256 or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("stage77_custody_evidence_identifier_invalid")
    return value

def ensure_custody_evidence_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS stage77_custody_evidence_sets (
      id TEXT PRIMARY KEY, mandate_id TEXT NOT NULL, report_id INTEGER NOT NULL, report_version_id INTEGER NOT NULL,
      job1_id INTEGER NOT NULL, job2_id INTEGER NOT NULL, runtime_json TEXT NOT NULL, payload_json TEXT NOT NULL,
      payload_digest TEXT NOT NULL UNIQUE, idempotency_key TEXT NOT NULL UNIQUE, state TEXT NOT NULL CHECK(state IN ('registered','consumed','invalidated','expired')),
      created_at TEXT NOT NULL, consumed_at TEXT, consumed_job_id INTEGER UNIQUE);
    CREATE TABLE IF NOT EXISTS stage77_custody_evidence_objects (
      evidence_set_id TEXT NOT NULL, role TEXT NOT NULL, object_id TEXT NOT NULL, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL, media_type TEXT NOT NULL,
      PRIMARY KEY(evidence_set_id,role), UNIQUE(evidence_set_id,object_id), FOREIGN KEY(evidence_set_id) REFERENCES stage77_custody_evidence_sets(id));
    CREATE TABLE IF NOT EXISTS stage77_custody_evidence_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, evidence_set_id TEXT NOT NULL, event_type TEXT NOT NULL, actor TEXT NOT NULL, occurred_at TEXT NOT NULL, payload_json TEXT NOT NULL,
      FOREIGN KEY(evidence_set_id) REFERENCES stage77_custody_evidence_sets(id));
    CREATE INDEX IF NOT EXISTS idx_stage77_custody_evidence_set_report
      ON stage77_custody_evidence_sets(report_id,report_version_id);
    CREATE INDEX IF NOT EXISTS idx_stage77_custody_evidence_events_set
      ON stage77_custody_evidence_events(evidence_set_id,id);
    CREATE TRIGGER IF NOT EXISTS stage77_custody_evidence_set_no_delete BEFORE DELETE ON stage77_custody_evidence_sets BEGIN SELECT RAISE(ABORT,'stage77_custody_evidence_immutable'); END;
    CREATE TRIGGER IF NOT EXISTS stage77_custody_evidence_set_authority_immutable
      BEFORE UPDATE OF id,mandate_id,report_id,report_version_id,job1_id,job2_id,runtime_json,payload_json,payload_digest,idempotency_key,created_at
      ON stage77_custody_evidence_sets BEGIN SELECT RAISE(ABORT,'stage77_custody_evidence_immutable'); END;
    CREATE TRIGGER IF NOT EXISTS stage77_custody_evidence_set_state_forward_only BEFORE UPDATE OF state ON stage77_custody_evidence_sets
      WHEN NOT ((OLD.state='registered' AND NEW.state IN ('consumed','invalidated','expired')))
      BEGIN SELECT RAISE(ABORT,'stage77_custody_evidence_transition_invalid'); END;
    CREATE TRIGGER IF NOT EXISTS stage77_custody_evidence_object_no_update BEFORE UPDATE ON stage77_custody_evidence_objects BEGIN SELECT RAISE(ABORT,'stage77_custody_evidence_immutable'); END;
    CREATE TRIGGER IF NOT EXISTS stage77_custody_evidence_object_no_delete BEFORE DELETE ON stage77_custody_evidence_objects BEGIN SELECT RAISE(ABORT,'stage77_custody_evidence_immutable'); END;
    CREATE TRIGGER IF NOT EXISTS stage77_custody_evidence_event_no_update BEFORE UPDATE ON stage77_custody_evidence_events BEGIN SELECT RAISE(ABORT,'stage77_custody_evidence_immutable'); END;
    CREATE TRIGGER IF NOT EXISTS stage77_custody_evidence_event_no_delete BEFORE DELETE ON stage77_custody_evidence_events BEGIN SELECT RAISE(ABORT,'stage77_custody_evidence_immutable'); END;
    """)

def evidence_root() -> Path:
    raw = os.environ.get("CDE_STAGE77_CUSTODY_EVIDENCE_V1_STORE_ROOT", "")
    if not raw or not os.path.isabs(raw): raise ValueError("stage77_custody_evidence_store_unavailable")
    root = Path(raw)
    if root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077:
        raise ValueError("stage77_custody_evidence_store_unavailable")
    return root

def _object_path(root: Path, evidence_set_id: str, role: str) -> Path:
    if not evidence_set_id or "/" in evidence_set_id or role not in ROLES:
        raise ValueError("stage77_custody_evidence_locator_invalid")
    path = root / evidence_set_id / (role + ".json")
    if path.is_symlink() or not path.is_file():
        raise ValueError("stage77_custody_evidence_object_missing")
    return path

def retained_object(root: Path, evidence_set_id: str, role: str) -> dict[str, Any]:
    """Read one fixed controller-owned object and return independently measured facts."""
    path = _object_path(root, evidence_set_id, role)
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size) != (after.st_dev, after.st_ino, after.st_size):
        raise ValueError("stage77_custody_evidence_object_changed")
    return {"role": role, "object_id": f"{evidence_set_id}:{role}", "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), "media_type": "application/json"}

def _register_verified(conn: sqlite3.Connection, *, payload: Mapping[str, Any], actor: str, occurred_at: str) -> dict[str, Any]:
    """Persist authority constructed by ``register_from_store`` only.

    Keeping this operation private prevents an admin caller from registering a
    self-declared payload in place of controller-retained evidence.
    """
    required = {"id", "mandate_id", "report_id", "report_version_id", "job1_id", "job2_id", "runtime", "objects", "facts", "authority", "idempotency_key", "payload_digest"}
    if set(payload) != required or not isinstance(payload["objects"], list):
        raise ValueError("stage77_custody_evidence_schema_invalid")
    if payload["payload_digest"] != digest(payload):
        raise ValueError("stage77_custody_evidence_digest_invalid")
    objects = payload["objects"]
    if {x.get("role") for x in objects if isinstance(x, dict)} != set(ROLES) or len(objects) != len(ROLES):
        raise ValueError("stage77_custody_evidence_roles_invalid")
    encoded = canonical(dict(payload)).decode()
    existing = conn.execute("SELECT * FROM stage77_custody_evidence_sets WHERE idempotency_key=?", (payload["idempotency_key"],)).fetchone()
    if existing:
        if existing["payload_digest"] != payload["payload_digest"]: raise ValueError("stage77_custody_evidence_idempotency_conflict")
        return dict(existing)
    # The public identity is also immutable authority.  A caller cannot evade
    # idempotency by reusing it with a different idempotency key or payload.
    existing = conn.execute("SELECT * FROM stage77_custody_evidence_sets WHERE id=?", (payload["id"],)).fetchone()
    if existing:
        if existing["payload_digest"] == payload["payload_digest"] and existing["idempotency_key"] == payload["idempotency_key"]:
            return dict(existing)
        raise ValueError("stage77_custody_evidence_identity_conflict")
    conn.execute("INSERT INTO stage77_custody_evidence_sets(id,mandate_id,report_id,report_version_id,job1_id,job2_id,runtime_json,payload_json,payload_digest,idempotency_key,state,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (payload["id"],payload["mandate_id"],payload["report_id"],payload["report_version_id"],payload["job1_id"],payload["job2_id"],canonical(payload["runtime"]).decode(),encoded,payload["payload_digest"],payload["idempotency_key"],"registered",occurred_at))
    for item in objects:
        conn.execute("INSERT INTO stage77_custody_evidence_objects(evidence_set_id,role,object_id,sha256,size_bytes,media_type) VALUES(?,?,?,?,?,?)", (payload["id"],item["role"],item["object_id"],item["sha256"],item["size_bytes"],item["media_type"]))
    conn.execute("INSERT INTO stage77_custody_evidence_events(evidence_set_id,event_type,actor,occurred_at,payload_json) VALUES(?,?,?,?,?)", (payload["id"],"evidence_registered",actor,occurred_at,encoded))
    return dict(conn.execute("SELECT * FROM stage77_custody_evidence_sets WHERE id=?", (payload["id"],)).fetchone())


def _required_fact(role: str, value: Any, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("stage77_custody_evidence_retained_fact_invalid")
    return value


def _utc_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("stage77_custody_evidence_capture_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ValueError("stage77_custody_evidence_capture_invalid") from None
    if parsed.tzinfo != timezone.utc:
        raise ValueError("stage77_custody_evidence_capture_invalid")
    return parsed


def register_from_store(conn: sqlite3.Connection, *, evidence_set_id: str, mandate_id: str, report_id: int, report_version_id: int, actor: str, occurred_at: str) -> dict[str, Any]:
    """Verify and register one controller-owned evidence package.

    The caller can select an existing mandate/report/version tuple, but every
    fact placed into the immutable registry is read from retained bytes, the
    persistence ledger, or the active runtime authority.  No caller value or
    manifest claim is accepted as corroboration by itself.
    """
    try:
        _identifier(evidence_set_id)
        _identifier(mandate_id)
    except ValueError:
        raise ValueError("stage77_custody_evidence_input_invalid") from None
    if not isinstance(report_id, int) or not isinstance(report_version_id, int):
        raise ValueError("stage77_custody_evidence_input_invalid")
    root = evidence_root(); package = root / evidence_set_id
    if package.is_symlink() or not package.is_dir(): raise ValueError("stage77_custody_evidence_store_unavailable")
    manifest_path = package / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file(): raise ValueError("stage77_custody_evidence_manifest_missing")
    manifest = strict_json(manifest_path.read_text("utf-8"))
    required_manifest = {
        "id", "mandate_id", "mandate_digest", "mandate_idempotency_key",
        "report_id", "report_version_id", "job1_id", "job2_id", "runtime",
        "capture_completed_at", "objects", "idempotency_key",
        "specification_digest", "qualification_id", "qualification_digest",
        "declaration", "rationale", "facts",
    }
    if set(manifest) != required_manifest:
        raise ValueError("stage77_custody_evidence_manifest_invalid")
    if manifest["id"] != evidence_set_id or manifest["mandate_id"] != mandate_id or manifest["report_id"] != report_id or manifest["report_version_id"] != report_version_id:
        raise ValueError("stage77_custody_evidence_binding_mismatch")
    if not all(isinstance(manifest[name], str) and manifest[name] for name in ("mandate_idempotency_key", "idempotency_key", "declaration", "rationale")) or not isinstance(manifest["qualification_id"], int):
        raise ValueError("stage77_custody_evidence_manifest_invalid")
    _sha256(manifest["mandate_digest"]); _sha256(manifest["specification_digest"]); _sha256(manifest["qualification_digest"])
    capture_at = _utc_timestamp(manifest["capture_completed_at"])
    if (datetime.now(timezone.utc) - capture_at).total_seconds() > 3600 or capture_at > datetime.now(timezone.utc):
        raise ValueError("stage77_custody_evidence_capture_stale")
    seen, objects, retained_facts = set(), [], {}
    for item in manifest["objects"]:
        if not isinstance(item, dict) or set(item) != {"role","filename","media_type"} or item["role"] in seen or item["role"] not in ROLES:
            raise ValueError("stage77_custody_evidence_roles_invalid")
        seen.add(item["role"]); name=item["filename"]
        if not isinstance(name,str) or "/" in name or name in {"", ".", ".."}: raise ValueError("stage77_custody_evidence_locator_invalid")
        path=package/name
        if path.is_symlink() or not path.is_file() or path.parent != package: raise ValueError("stage77_custody_evidence_object_missing")
        before = path.stat(); data = path.read_bytes(); after = path.stat()
        if (before.st_dev, before.st_ino, before.st_size) != (after.st_dev, after.st_ino, after.st_size):
            raise ValueError("stage77_custody_evidence_object_changed")
        if item["media_type"] != "application/json":
            raise ValueError("stage77_custody_evidence_object_invalid")
        try:
            retained_facts[item["role"]] = strict_json(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ValueError("stage77_custody_evidence_retained_fact_invalid") from None
        objects.append({"role":item["role"],"object_id":evidence_set_id+":"+item["role"],"sha256":hashlib.sha256(data).hexdigest(),"size_bytes":len(data),"media_type":item["media_type"]})
    if seen != set(ROLES): raise ValueError("stage77_custody_evidence_roles_invalid")
    if manifest["facts"] != retained_facts:
        raise ValueError("stage77_custody_evidence_retained_fact_mismatch")

    # Independently resolve the application authority; the manifest cannot
    # select or replace any of these values.
    from api import governed_report_jobs as jobs
    from api import governed_report_qualifications as qualification_store
    mandate = conn.execute("SELECT * FROM stage77_custody_v2_mandates WHERE id=?", (mandate_id,)).fetchone()
    if mandate is None or mandate["state"] != "created" or int(mandate["report_id"]) != report_id or int(mandate["report_version_id"]) != report_version_id:
        raise ValueError("stage77_custody_evidence_mandate_invalid")
    if mandate["mandate_digest"] != manifest["mandate_digest"] or mandate["idempotency_key"] != manifest["mandate_idempotency_key"]:
        raise ValueError("stage77_custody_evidence_mandate_mismatch")
    mandate_payload = strict_json(str(mandate["mandate_json"]))
    report = jobs.reports.get_report(conn, report_id)
    version = report["versions"][-1]
    if int(version["id"]) != report_version_id or report["lifecycle_status"] != "validation_failed":
        raise ValueError("stage77_custody_evidence_report_invalid")
    job1, job2, topology = jobs._post_correction_topology(conn, report_id, report_version_id)
    if (manifest["job1_id"], manifest["job2_id"]) != (int(job1["id"]), int(job2["id"])) or (int(mandate["predecessor_job_1_id"]), int(mandate["predecessor_job_2_id"])) != (int(job1["id"]), int(job2["id"])):
        raise ValueError("stage77_custody_evidence_job_topology_invalid")
    if mandate_payload.get("predecessor_job_ids") != [int(job1["id"]), int(job2["id"])] or mandate_payload.get("topology_digest") != topology:
        raise ValueError("stage77_custody_evidence_job_topology_invalid")
    qualification = qualification_store.latest_final(conn, report_id)
    if qualification is None or (manifest["qualification_id"], manifest["qualification_digest"]) != (int(qualification["id"]), str(qualification["digest"])):
        raise ValueError("stage77_custody_evidence_qualification_invalid")
    if (manifest["specification_digest"] != str(version["specification_digest"]) or jobs.reports.specification_digest(version["specification"]) != manifest["specification_digest"]):
        raise ValueError("stage77_custody_evidence_specification_invalid")
    required_mandate = {
        "report_id": report_id, "report_version_id": report_version_id,
        "purpose": PURPOSE, "specification_digest": manifest["specification_digest"],
        "qualification_id": manifest["qualification_id"], "qualification_digest": manifest["qualification_digest"],
        "declaration": manifest["declaration"], "rationale": manifest["rationale"],
    }
    if any(mandate_payload.get(key) != value for key, value in required_mandate.items()) or mandate["declaration"] != manifest["declaration"] or mandate["rationale"] != manifest["rationale"]:
        raise ValueError("stage77_custody_evidence_mandate_mismatch")
    runtime = jobs.custody_v2_runtime_authority()
    if manifest["runtime"] != runtime or mandate_payload.get("runtime") != runtime or retained_facts["runtime_authority"] != runtime:
        raise ValueError("stage77_custody_evidence_runtime_mismatch")

    database = _required_fact("database_capture", retained_facts["database_capture"], {"database_id", "capture_digest", "capture_completed_at"})
    database_digest = _required_fact("database_digest", retained_facts["database_digest"], {"database_id", "capture_digest"})
    checkpoint = _required_fact("checkpoint_wal_shm", retained_facts["checkpoint_wal_shm"], {"database_id", "checkpoint", "wal", "shm"})
    points = _required_fact("custody_points_1_5", retained_facts["custody_points_1_5"], {"points_1_5_id", "points_1_5_digest"})
    archive = _required_fact("archive_export", retained_facts["archive_export"], {"archive_id", "archive_digest", "export_id", "export_digest"})
    receipt = _required_fact("receipt", retained_facts["receipt"], {"receipt_id", "receipt_digest", "archive_digest", "export_digest"})
    recovery = _required_fact("recovery_verification", retained_facts["recovery_verification"], {"recovery_verification_id", "recovery_verification_digest", "database_id", "capture_digest"})
    inventory = _required_fact("artifact_inventory", retained_facts["artifact_inventory"], {"artifact_inventory_id", "artifact_inventory_digest"})
    if (database["database_id"] != database_digest["database_id"] or database["capture_digest"] != database_digest["capture_digest"] or database["capture_completed_at"] != manifest["capture_completed_at"] or checkpoint["database_id"] != database["database_id"] or recovery["database_id"] != database["database_id"] or recovery["capture_digest"] != database["capture_digest"] or receipt["archive_digest"] != archive["archive_digest"] or receipt["export_digest"] != archive["export_digest"]):
        raise ValueError("stage77_custody_evidence_cross_binding_invalid")
    for facts_digest in (
        database["capture_digest"], database_digest["capture_digest"], points["points_1_5_digest"],
        archive["archive_digest"], archive["export_digest"], receipt["receipt_digest"],
        recovery["recovery_verification_digest"], inventory["artifact_inventory_digest"],
    ):
        _sha256(facts_digest)
    if not all(isinstance(value, str) and value for value in (
        database["database_id"], points["points_1_5_id"], archive["archive_id"], archive["export_id"],
        receipt["receipt_id"], recovery["recovery_verification_id"], inventory["artifact_inventory_id"],
        checkpoint["checkpoint"], checkpoint["wal"], checkpoint["shm"],
    )):
        raise ValueError("stage77_custody_evidence_retained_fact_invalid")
    facts = {
        "database": database, "checkpoint_wal_shm": checkpoint, "points_1_5": points,
        "archive_export": archive, "receipt": receipt, "recovery_verification": recovery,
        "artifact_inventory": inventory,
    }
    payload = {key: manifest[key] for key in ("id", "mandate_id", "report_id", "report_version_id", "job1_id", "job2_id", "runtime", "idempotency_key")}
    payload["objects"] = objects
    payload["facts"] = facts
    payload["authority"] = {
        "mandate_digest": str(mandate["mandate_digest"]),
        "mandate_idempotency_key": str(mandate["idempotency_key"]),
        "specification_digest": str(version["specification_digest"]),
        "qualification_id": int(qualification["id"]),
        "qualification_digest": str(qualification["digest"]),
        "declaration": str(mandate["declaration"]), "rationale": str(mandate["rationale"]),
        "capture_completed_at": manifest["capture_completed_at"], "topology_digest": topology,
    }
    payload["payload_digest"] = digest(payload)
    return _register_verified(conn, payload=payload, actor=actor, occurred_at=occurred_at)
