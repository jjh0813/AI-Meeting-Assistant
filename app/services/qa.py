from app.core.prompts import RAG_QA_PROMPT
from app.services.llm import call_llm


def answer_from_meetings(question: str, sources: list[dict]) -> str:
    context = "\n\n".join(
        f"[회의록 #{source['id']} · {source['source_type']}]\n{source['content']}"
        for source in sources
    )
    prompt = RAG_QA_PROMPT.format(question=question, sources=context)
    return call_llm(prompt)
