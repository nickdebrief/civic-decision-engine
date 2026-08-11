import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException
from tests.test_admin_session import install_fastapi_stubs

from api import record_document_association_decisions as decisions
install_fastapi_stubs()
from api.routes import admin_session


class Stage611DiagnosticTests(unittest.TestCase):
    DOC_A = "a" * 64
    DOC_B = "b" * 64

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "intake"
        self.root.mkdir()
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self._write_document(self.DOC_A, "Document A", "DOC-2026-000118")
        self._write_document(self.DOC_B, "Document B", "DOC-2026-000123")

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def _create_tables(self, *, decisions_table=True):
        self.conn.executescript(
            """
            CREATE TABLE record_document_associations (
                id INTEGER PRIMARY KEY,
                public_reference TEXT,
                record_reference TEXT NOT NULL,
                document_id TEXT NOT NULL,
                document_reference_identifier TEXT,
                relationship_type TEXT NOT NULL,
                public_label TEXT NOT NULL,
                public_note TEXT,
                admin_note TEXT,
                is_active INTEGER NOT NULL,
                is_public INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT NOT NULL
            );
            """,
        )
        self.conn.execute(
            """
            INSERT INTO record_document_associations VALUES
                (66, 'CDE-ASSOC-20260811-001', 'CLE-UHL-20180619-001', ?, NULL,
                 'supporting_document', 'Supporting document', 'Public note',
                 'Private note', 1, 1, '2026-08-11T14:00:08Z', 'nick',
                 '2026-08-11T14:00:08Z', 'nick')
            """,
            (self.DOC_A,),
        )
        self.conn.execute(
            """
            CREATE TABLE record_document_association_history (
                id INTEGER PRIMARY KEY,
                association_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                actor TEXT NOT NULL,
                previous_state_json TEXT,
                new_state_json TEXT,
                note TEXT
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO record_document_association_history VALUES
                (1, 66, 'created', '2026-08-11T14:00:08Z', 'nick', NULL,
                 '{"is_active":true}', 'Historical note')
            """
        )
        if decisions_table:
            decisions.ensure_decision_table(self.conn)
        self.conn.commit()

    def _write_document(self, intake_id, title, identifier):
        directory = self.root / intake_id
        directory.mkdir()
        (directory / "metadata.json").write_text(
            json.dumps(
                {
                    "intake_id": intake_id,
                    "title": title,
                    "document_identifier": identifier,
                    "status": "published",
                    "document_type": "pdf",
                }
            ),
            encoding="utf-8",
        )

    def _insert_decision(
        self,
        *,
        document_id=None,
        decision_type="association_created",
        decided_at="2026-08-11T14:00:08Z",
        key="rda-abcdefghijklmnopqrstuvwxyz1234567890",
        rationale="Created during verification.",
        association_id=66,
        payload_values=None,
    ):
        payload = {
            "association_id": None,
            "decision_type": decision_type,
            "actor": "nick",
            "actor_role": "admin",
            "rationale": rationale,
            "record_reference": "CLE-UHL-20180619-001",
            "document_id": document_id or self.DOC_A,
            "relationship_type": "supporting_document",
        }
        payload.update(payload_values or {})
        self.conn.execute(
            """
            INSERT INTO record_document_association_decisions (
                association_id, idempotency_key, decision_type,
                previous_state_json, resulting_state_json, actor, actor_role,
                decided_at, rationale, evidence_references_json, context_reference,
                request_payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                association_id,
                key,
                decision_type,
                None,
                json.dumps({"is_active": True, "relationship_type": "supporting_document"}),
                "nick",
                "admin",
                decided_at,
                rationale,
                "[]",
                None,
                json.dumps(payload),
            ),
        )
        self.conn.commit()

    def _read(self):
        return decisions.read_association_decision_diagnostic(
            66, db_path=self.db_path, document_root=self.root
        )

    def test_authenticated_route_renders_and_unauthenticated_access_is_denied(self):
        request = object()
        with patch.object(
            admin_session, "require_admin_session", side_effect=HTTPException(status_code=401)
        ):
            with self.assertRaises(HTTPException):
                admin_session.admin_association_decision_diagnostic(66, request)

        self._insert_decision()
        diagnostic = self._read()
        with patch.object(admin_session, "require_admin_session", return_value={"username": "nick", "role": "admin"}), patch.object(
            admin_session.rdd, "read_association_decision_diagnostic", return_value=diagnostic
        ):
            response = admin_session.admin_association_decision_diagnostic(66, request)
        self.assertEqual(response.status_code, 200)
        rendered = getattr(response, "body", getattr(response, "content", b""))
        rendered = rendered.decode() if isinstance(rendered, bytes) else rendered
        self.assertIn("Governed Decision Diagnostic", rendered)

    def test_missing_decision_table_remains_absent_and_no_commit_or_ddl_occurs(self):
        missing_path = Path(self.temp_dir.name) / "missing-decisions.db"
        missing = sqlite3.connect(missing_path)
        missing.execute(
            "CREATE TABLE record_document_associations (id INTEGER PRIMARY KEY, document_id TEXT NOT NULL)"
        )
        missing.execute(
            "INSERT INTO record_document_associations VALUES (?, ?)", (66, self.DOC_A)
        )
        missing.commit()
        missing.close()
        before = sqlite3.connect(missing_path).execute(
            "SELECT name, sql FROM sqlite_master ORDER BY name"
        ).fetchall()
        result = decisions.read_association_decision_diagnostic(
            66, db_path=missing_path, document_root=self.root
        )
        after_conn = sqlite3.connect(missing_path)
        after = after_conn.execute(
            "SELECT name, sql FROM sqlite_master ORDER BY name"
        ).fetchall()
        after_conn.close()
        self.assertFalse(result["decision_table_present"])
        self.assertEqual(before, after)
        self.assertIn("Stage 61 decision persistence is not present", result["warnings"])

    def test_creation_decision_is_redacted_and_raw_document_ids_compare(self):
        self._insert_decision(document_id=self.DOC_A)
        result = self._read()
        decision = result["decisions"][0]
        self.assertEqual(result["comparison"]["state"], "YES")
        self.assertEqual(decision["request_payload"]["document_id"], self.DOC_A)
        self.assertEqual(decision["request_payload"]["decision_type"], "association_created")
        self.assertEqual(decision["idempotency_key_fingerprint"], "rda-abcd…34567890")
        rendered = admin_session._render_association_decision_diagnostic(result)
        self.assertIn(self.DOC_A, rendered)
        self.assertIn("DOC-2026-000118", rendered)
        self.assertNotIn("rda-abcdefghijklmnopqrstuvwxyz1234567890", rendered)
        self.assertIn("Stage 60 GovernedDecision projection", rendered)

    def test_differing_document_ids_produce_no_and_incomplete_is_not_determinable(self):
        self._insert_decision(document_id=self.DOC_B)
        result = self._read()
        self.assertEqual(result["comparison"]["state"], "NO")
        self.assertIn("Creation payload document does not match association document", result["warnings"])

        self.conn.execute("DELETE FROM record_document_association_decisions")
        self.conn.execute(
            "UPDATE record_document_association_decisions SET request_payload_json = ?",
            ("{}",),
        )
        self.conn.commit()
        result = self._read()
        self.assertEqual(result["comparison"]["state"], "NOT DETERMINABLE")

    def test_malformed_unknown_unresolved_and_multiple_creation_rows_are_observational(self):
        self._insert_decision(decision_type="association_created", key="first-key")
        self.conn.execute(
            "UPDATE record_document_association_decisions SET request_payload_json = ? WHERE id = 1",
            ("{malformed",),
        )
        self._insert_decision(decision_type="association_created", key="second-key", decided_at="2026-08-11T14:01:08Z")
        self._insert_decision(decision_type="unexpected", key="unknown-key", decided_at="2026-08-11T14:02:08Z")
        before = self.conn.execute(
            "SELECT COUNT(*) FROM record_document_association_decisions"
        ).fetchone()[0]
        result = self._read()
        after = self.conn.execute(
            "SELECT COUNT(*) FROM record_document_association_decisions"
        ).fetchone()[0]
        self.assertEqual(before, after)
        self.assertIn("Multiple association_created decisions exist", result["warnings"])
        self.assertTrue(any("Malformed request payload" in warning for warning in result["warnings"]))
        self.assertTrue(any("Unknown decision type" in warning for warning in result["warnings"]))

    def test_multiple_decisions_are_ordered_and_history_is_unchanged(self):
        self._insert_decision(decided_at="2026-08-11T14:02:08Z", key="later")
        self._insert_decision(decision_type="relationship_reclassified", decided_at="2026-08-11T14:01:08Z", key="earlier")
        before_history = self.conn.execute(
            "SELECT * FROM record_document_association_history ORDER BY id"
        ).fetchall()
        result = self._read()
        after_history = self.conn.execute(
            "SELECT * FROM record_document_association_history ORDER BY id"
        ).fetchall()
        self.assertEqual(
            [item["decided_at"] for item in result["decisions"]],
            ["2026-08-11T14:01:08Z", "2026-08-11T14:02:08Z"],
        )
        self.assertEqual(before_history, after_history)

    def test_public_association_route_does_not_receive_diagnostic_fields(self):
        from api.routes import associations as public_routes

        row = {
            "id": 66,
            "public_reference": "CDE-ASSOC-20260811-001",
            "record_reference": "CLE-UHL-20180619-001",
            "document_id": self.DOC_A,
            "relationship_type": "supporting_document",
            "public_label": "Supporting document",
            "public_note": "Public note",
            "created_at": "2026-08-11T14:00:08Z",
            "created_by": "nick",
            "is_active": 1,
            "is_public": 1,
            "record_title": "Public record",
            "document_title": "Document A",
            "document_reference_identifier": None,
            "record_publicly_eligible": True,
            "document_publicly_eligible": True,
        }
        connection = Mock()
        with patch.object(public_routes.rda, "get_db", return_value=connection), patch.object(
            public_routes.rda, "get_public_association", return_value=row
        ), patch.object(public_routes.rda, "public_association_history", return_value=[]):
            response = public_routes.public_association_page(row["public_reference"])
        content = getattr(response, "body", getattr(response, "content", ""))
        content = content.decode() if isinstance(content, bytes) else content
        for secret in ("record-document-association-decision:", "request_payload", "actor_role", "rda-abcdefghijklmnopqrstuvwxyz1234567890"):
            self.assertNotIn(secret, content)

    def test_reader_uses_read_only_sqlite_uri(self):
        real_connect = sqlite3.connect
        calls = []

        def traced_connect(*args, **kwargs):
            calls.append((args, kwargs))
            return real_connect(*args, **kwargs)

        with patch.object(decisions.sqlite3, "connect", side_effect=traced_connect):
            self._read()

        self.assertEqual(len(calls), 1)
        self.assertIn("mode=ro", calls[0][0][0])
        self.assertTrue(calls[0][1]["uri"])

    def test_reader_executes_no_write_sql_and_never_commits(self):
        real_connect = sqlite3.connect

        class TracedConnection:
            def __init__(self, connection):
                self.connection = connection
                self.statements = []
                self.commits = 0

            @property
            def row_factory(self):
                return self.connection.row_factory

            @row_factory.setter
            def row_factory(self, value):
                self.connection.row_factory = value

            def execute(self, sql, parameters=()):
                self.statements.append(str(sql))
                return self.connection.execute(sql, parameters)

            def commit(self):
                self.commits += 1
                return self.connection.commit()

            def close(self):
                return self.connection.close()

        traced_connections = []

        def traced_connect(*args, **kwargs):
            traced = TracedConnection(real_connect(*args, **kwargs))
            traced_connections.append(traced)
            return traced

        with patch.object(decisions.sqlite3, "connect", side_effect=traced_connect):
            self._read()

        self.assertEqual(len(traced_connections), 1)
        traced = traced_connections[0]
        self.assertEqual(traced.commits, 0)
        writes = {"CREATE", "ALTER", "INSERT", "UPDATE", "DELETE", "REPLACE", "DROP"}
        for statement in traced.statements:
            first_keyword = statement.lstrip().split(None, 1)[0].upper()
            self.assertNotIn(first_keyword, writes, statement)

    def test_authentication_precedes_diagnostic_reader(self):
        request = object()
        with patch.object(
            admin_session,
            "require_admin_session",
            side_effect=HTTPException(status_code=401),
        ), patch.object(
            admin_session.rdd,
            "read_association_decision_diagnostic",
        ) as reader:
            with self.assertRaises(HTTPException):
                admin_session.admin_association_decision_diagnostic(66, request)
        reader.assert_not_called()

    def test_hostile_payload_and_rationale_are_escaped_without_storage_change(self):
        hostile = '<script>alert("x")</script>'
        self._insert_decision(
            rationale=hostile,
            payload_values={"record_reference": hostile},
        )
        before = self.conn.execute(
            "SELECT rationale, request_payload_json FROM record_document_association_decisions"
        ).fetchone()
        rendered = admin_session._render_association_decision_diagnostic(self._read())
        after = self.conn.execute(
            "SELECT rationale, request_payload_json FROM record_document_association_decisions"
        ).fetchone()
        self.assertNotIn(hostile, rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertEqual(before, after)

    def test_unresolved_document_keeps_raw_id_and_comparison_uses_raw_value(self):
        unresolved = "u" * 64
        self.conn.execute(
            "UPDATE record_document_associations SET document_id = ? WHERE id = 66",
            (unresolved,),
        )
        self.conn.commit()
        before = self.conn.execute(
            "SELECT document_id FROM record_document_associations WHERE id = 66"
        ).fetchone()[0]
        self._insert_decision(document_id=unresolved)
        result = self._read()
        rendered = admin_session._render_association_decision_diagnostic(result)
        after = self.conn.execute(
            "SELECT document_id FROM record_document_associations WHERE id = 66"
        ).fetchone()[0]
        self.assertEqual(result["comparison"]["state"], "YES")
        self.assertFalse(result["association_document"]["resolved"])
        self.assertIn(unresolved, rendered)
        self.assertEqual(before, after)

    def test_decision_for_another_association_is_not_reinterpreted(self):
        self._insert_decision(
            association_id=67,
            key="mismatched-association-key",
            payload_values={"association_id": 67},
        )
        before = self.conn.execute(
            "SELECT association_id, request_payload_json FROM record_document_association_decisions"
        ).fetchall()
        result = self._read()
        rendered = admin_session._render_association_decision_diagnostic(result)
        after = self.conn.execute(
            "SELECT association_id, request_payload_json FROM record_document_association_decisions"
        ).fetchall()
        self.assertEqual(result["decisions"], [])
        self.assertIn("No Stage 61 decisions exist", rendered)
        self.assertEqual(before, after)

    def test_missing_decision_table_through_authenticated_route_remains_absent(self):
        missing_path = Path(self.temp_dir.name) / "route-missing-decisions.db"
        missing = sqlite3.connect(missing_path)
        missing.execute(
            "CREATE TABLE record_document_associations (id INTEGER PRIMARY KEY, document_id TEXT NOT NULL)"
        )
        missing.execute(
            "INSERT INTO record_document_associations VALUES (?, ?)", (66, self.DOC_A)
        )
        missing.commit()
        missing.close()
        request = object()
        with patch.object(
            admin_session,
            "require_admin_session",
            return_value={"username": "nick", "role": "admin"},
        ), patch.object(admin_session, "DB_PATH", missing_path):
            response = admin_session.admin_association_decision_diagnostic(66, request)
        schema = sqlite3.connect(missing_path)
        tables = schema.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        schema.close()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(("record_document_association_decisions",), tables)
        body = getattr(response, "body", getattr(response, "content", ""))
        body = body.decode() if isinstance(body, bytes) else body
        self.assertIn("Stage 61 decision persistence is not present", body)


if __name__ == "__main__":
    unittest.main()
