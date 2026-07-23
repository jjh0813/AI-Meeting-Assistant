import unittest

from app.services.retrieval import (
    answer_indicates_missing_evidence,
    has_sufficient_evidence,
    lexical_similarity,
    rerank_sources,
)


class RetrievalTests(unittest.TestCase):
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

    def test_missing_evidence_answer_is_detected(self):
        self.assertTrue(
            answer_indicates_missing_evidence(
                "해당 내용은 회의록에서 확인할 수 없습니다."
            )
        )


if __name__ == "__main__":
    unittest.main()
