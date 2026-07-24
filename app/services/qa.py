from app.core.prompts import RAG_QA_PROMPT
from app.services.llm import call_llm


def answer_from_meetings(
    question: str, sources: list[dict], current_user_name: str
) -> str:
    context = "\n\n".join(
        f"[회의록 #{source['id']} · {source['source_type']}]\n{source['content']}"
        for source in sources
    )
    prompt = RAG_QA_PROMPT.format(
        question=question,
        sources=context,
        current_user_name=current_user_name,
    )
    return call_llm(prompt)
