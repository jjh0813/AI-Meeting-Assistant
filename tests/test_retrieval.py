import unittest
from unittest.mock import Mock, patch

from app.api.routes.transcripts import find_rag_sources
from app.services.retrieval import (
    allows_semantic_only_evidence,
    answer_indicates_missing_evidence,
    best_excerpt,
    asks_for_personal_tasks,
    has_sufficient_evidence,
    lexical_similarity,
    rerank_sources,
)


class RetrievalTests(unittest.TestCase):
    @patch("app.api.routes.transcripts.transcript_repo.search_action_items_for_qa")
    @patch("app.api.routes.transcripts.transcript_repo.search_similar_summaries")
    @patch("app.api.routes.transcripts.transcript_repo.search_similar_chunks")
    def test_selected_retriever_skips_unselected_database_searches(
        self, search_chunks, search_summaries, search_tasks
    ):
        search_tasks.return_value = []

        results = find_rag_sources(
            Mock(),
            Mock(),
            "내 담당 업무",
            [0.1] * 768,
            limit=3,
            source_types={"action_item"},
        )

        self.assertEqual(results, [])
        search_chunks.assert_not_called()
        search_summaries.assert_not_called()
        search_tasks.assert_called_once()

    def test_best_excerpt_keeps_the_most_relevant_sentences(self):
        content = (
            "회의를 시작했습니다. "
            "배포 일정은 8월 3일로 결정했습니다. "
            "김철수님이 배포 전 점검을 담당합니다."
        )

        excerpt = best_excerpt("배포 일정과 담당자는?", content)

        self.assertIn("배포 일정은 8월 3일", excerpt)
        self.assertIn("김철수님이 배포 전 점검", excerpt)
        self.assertNotIn("회의를 시작했습니다", excerpt)

    def test_domain_aliases_match_paraphrased_erp_question(self):
        score = lexical_similarity(
            "새 회계 시스템으로 바꾸는 날짜가 언제지?",
            "신규 회계 ERP 운영 전환일은 9월 15일로 확정했다.",
        )

        self.assertGreaterEqual(score, 0.8)

    def test_lexical_reranking_promotes_matching_source(self):
        sources = [
            {"id": 1, "content": "외부감사 자료를 준비한다.", "similarity": 0.78},
            {
                "id": 2,
                "content": "출장 숙박비 한도는 1박 15만원이다.",
                "similarity": 0.74,
            },
        ]

        results = rerank_sources("출장 숙박비 한도는?", sources, limit=2)

        self.assertEqual(results[0]["id"], 2)

    def test_weak_lexical_match_is_not_sufficient_evidence(self):
        source = {
            "similarity": 0.88,
            "lexical_similarity": 0.20,
            "retrieval_score": 0.642,
        }

        self.assertFalse(has_sufficient_evidence(source))

    def test_common_task_question_allows_semantic_evidence(self):
        source = {
            "similarity": 0.70,
            "lexical_similarity": 0.0,
            "retrieval_score": 0.455,
        }

        self.assertTrue(allows_semantic_only_evidence("내가 맡은 업무를 알려줘"))
        self.assertTrue(
            has_sufficient_evidence(source, allow_semantic_only=True)
        )
        self.assertTrue(asks_for_personal_tasks("내가 맡은 업무를 알려줘"))
        self.assertFalse(
            asks_for_personal_tasks("회의에서 정해진 담당 업무를 알려줘")
        )

    def test_unresolved_question_allows_semantic_evidence(self):
        self.assertTrue(
            allows_semantic_only_evidence("아직 정해지지 않은 내용은 뭐야?")
        )

    def test_unrelated_question_keeps_strict_evidence_threshold(self):
        source = {
            "similarity": 0.70,
            "lexical_similarity": 0.0,
            "retrieval_score": 0.455,
        }

        self.assertFalse(allows_semantic_only_evidence("오늘 점심은 뭐야?"))
        self.assertFalse(has_sufficient_evidence(source))

    def test_missing_evidence_answer_is_detected(self):
        self.assertTrue(
            answer_indicates_missing_evidence(
                "해당 내용은 회의록에서 확인할 수 없습니다."
            )
        )


if __name__ == "__main__":
    unittest.main()
