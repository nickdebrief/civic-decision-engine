import unittest
from unittest.mock import patch

from tests.test_admin_session import install_fastapi_stubs

install_fastapi_stubs()

from api.document_lifecycle_presentation import build_lifecycle_presentation
from api.routes import admin_session, documents


class Stage59LifecycleEpisodePresentationTests(unittest.TestCase):
    def setUp(self):
        self.item = {
            "intake_id": "intake-1",
            "title": "Reconsidered document",
            "institution_source": "Civic Office",
            "category": "Decision",
            "description": "Public description.",
            "document_identifier": "DOC-2026-000131",
            "reference_identifier": "REF-131",
            "publication_date": "2026-08-10T12:00:00Z",
            "status": "published",
        }
        self.original_decisions = [
            {"decision_sequence": 1, "episode_id": None, "new_status": "under_review"},
            {"decision_sequence": 2, "episode_id": None, "new_status": "rejected"},
            {"decision_sequence": 3, "episode_id": None, "new_status": "archived"},
        ]
        self.episode = {
            "episode_id": "LEP-episode-2",
            "episode_sequence": 2,
            "episode_type": "reconsideration",
            "initial_status": "pending",
            "initiated_at": "2026-08-10T09:00:00Z",
            "rationale": "Governed reconsideration.",
        }
        self.episode_decisions = [
            {"decision_sequence": 4, "episode_id": "LEP-episode-2", "new_status": "under_review"},
            {"decision_sequence": 5, "episode_id": "LEP-episode-2", "new_status": "approved"},
            {"decision_sequence": 6, "episode_id": "LEP-episode-2", "new_status": "published"},
        ]

    def test_implicit_episode_one_is_read_time_only(self):
        presentation = build_lifecycle_presentation(
            item={**self.item, "status": "archived"},
            decisions=self.original_decisions,
            episodes=[],
        )
        self.assertEqual(presentation["episodes"][0]["episode_id"], None)
        self.assertEqual(presentation["episodes"][0]["current_status"], "archived")
        self.assertFalse(presentation["has_reconsideration"])

    def test_episode_boundaries_and_current_publication_are_distinct(self):
        presentation = build_lifecycle_presentation(
            item=self.item,
            decisions=[*self.original_decisions, *self.episode_decisions],
            episodes=[self.episode],
        )
        self.assertEqual(
            [episode["label"] for episode in presentation["episodes"]],
            ["Episode 1 — Original consideration", "Episode 2 — Governed reconsideration"],
        )
        self.assertEqual(presentation["current_episode"]["sequence"], 2)
        self.assertEqual(presentation["public_lifecycle_summary"], "Published · Governed reconsideration")
        self.assertEqual(
            [event["new_status"] for event in presentation["episodes"][0]["decisions"]],
            ["under_review", "rejected", "archived"],
        )
        self.assertEqual(
            [event["new_status"] for event in presentation["episodes"][1]["decisions"]],
            ["under_review", "approved", "published"],
        )

    def test_library_uses_compact_public_lifecycle_summary_without_internal_id(self):
        presentation = build_lifecycle_presentation(
            item=self.item,
            decisions=[*self.original_decisions, *self.episode_decisions],
            episodes=[self.episode],
        )
        with patch.object(documents, "_public_lifecycle_presentation", return_value=presentation):
            content = documents._render_library(
                [self.item], [self.item], query=None, institution=None,
                category=None, publication_year=None,
            )
        self.assertIn("Published · Governed reconsideration", content)
        self.assertIn("DOC-2026-000131", content)
        self.assertNotIn("LEP-episode-2", content)
        self.assertNotIn("1040px", content)
        self.assertNotIn("Archived → Pending", content)
        self.assertIn("class=\"library-document-row\"", content)

    def test_library_wraps_long_titles_and_metadata_without_losing_identity(self):
        difficult_title = {
            **self.item,
            "intake_id": "intake-long-token",
            "title": "UN_ESCALATION_PRI_ACCESS_NICK_MOLONEY.pdf",
            "institution_source": "An institution or source name that is long enough to test intrinsic grid sizing safely",
            "category": "A category with a deliberately long readable value",
            "reference_identifier": "REFERENCE-WITH-A-LONG-VALUE-THAT-MUST-REMAIN-VISIBLE",
        }
        spaced_title = {
            **self.item,
            "intake_id": "intake-long-spaces",
            "title": "A document title with many ordinary words that must wrap inside its own column",
        }
        with patch.object(
            documents,
            "_public_lifecycle_presentation",
            return_value=build_lifecycle_presentation(item=self.item),
        ):
            content = documents._render_library(
                [difficult_title, spaced_title],
                [difficult_title, spaced_title],
                query=None,
                institution=None,
                category=None,
                publication_year=None,
            )
        self.assertIn("UN_ESCALATION_PRI_ACCESS_NICK_MOLONEY.pdf", content)
        self.assertIn("A document title with many ordinary words", content)
        self.assertIn("DOC-2026-000131", content)
        self.assertIn("minmax(0,1.2fr)", content)
        self.assertIn(
            ".library-document-primary,.library-document-secondary,.library-document-description,.library-document-action{min-width:0}",
            content,
        )
        self.assertIn(".library-document-primary h2{", content)
        self.assertIn("overflow-wrap:anywhere", content)
        self.assertIn("@media(max-width:600px)", content)
        self.assertIn("class=\"library-document-action\"", content)

    def test_public_provenance_selects_active_episode_decisions(self):
        item = {
            **self.item,
            "upload_date": "2026-08-01T09:00:00Z",
            "document_date": "2026-08-01",
            "original_filename": "document.pdf",
            "file_size_bytes": 10,
            "sha256_hash": "a" * 64,
            "sha512_hash": None,
            "document_type": "pdf",
            "metadata": {},
            "status_history": [],
        }
        presentation = build_lifecycle_presentation(
            item=item,
            decisions=[
                *self.original_decisions,
                *self.episode_decisions,
            ],
            episodes=[self.episode],
        )
        content = documents._render_publication_provenance
        with patch.object(documents, "_public_lifecycle_presentation", return_value=presentation):
            rendered = content(item)
        self.assertIn("Current lifecycle", rendered)
        self.assertIn("Published · Governed reconsideration", rendered)

    def test_administrative_audit_labels_episode_scoped_evidence(self):
        event = {
            "id": 1,
            "decision_key": "d" * 64,
            "intake_id": self.item["intake_id"],
            "decision_sequence": 4,
            "episode_id": "LEP-episode-2",
            "previous_status": "pending",
            "new_status": "under_review",
            "decided_at": "2026-08-10T10:00:00Z",
            "actor": "admin",
            "actor_role": "administrator",
            "rationale": "Review began.",
            "sha256_hash": None,
        }
        item = {
            **self.item,
            "status": "under_review",
            "status_updated_at": "2026-08-10T10:00:00Z",
            "active_episode_id": "LEP-episode-2",
            "status_history": [{
                "previous_status": "pending",
                "new_status": "under_review",
                "timestamp": "2026-08-10T10:00:00Z",
                "actor": "admin",
                "note": "Review began.",
                "lifecycle_decision_key": "d" * 64,
            }],
        }
        with patch.object(
            admin_session,
            "list_lifecycle_episodes",
            return_value=[self.episode],
        ), patch.object(
            admin_session,
            "_durable_current_lifecycle_episode_id",
            return_value="LEP-episode-2",
        ):
            events = admin_session._collect_admin_audit_events([item], [event])
        self.assertEqual(events[0]["episode_label"], "Episode 2 — Governed reconsideration")
        self.assertEqual(events[0]["evidence_source"], "Durable decision record — correctly projected")


if __name__ == "__main__":
    unittest.main()
