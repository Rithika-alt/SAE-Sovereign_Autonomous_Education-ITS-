"""Searcher agent: enriches lesson content via ChromaDB retrieval and Ollama synthesis."""

import os
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage

from agents.tutor_agent import SovereigntyError
from memory.chroma_store import add_documents, query_documents, collection_exists

load_dotenv()


class SearcherAgent:
    """Retrieves or synthesises supplementary learning material for a concept."""

    def __init__(self) -> None:
        """Initialise the searcher with a local Ollama LLM."""
        self.base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model: str = os.getenv("OLLAMA_MODEL", "llama3.2")
        if not (
            self.base_url.startswith("http://localhost")
            or self.base_url.startswith("http://127.0.0.1")
        ):
            raise SovereigntyError(
                f"OLLAMA_BASE_URL '{self.base_url}' is not localhost."
            )
        self._llm = ChatOllama(model=self.model, base_url=self.base_url)

    def _generate_chunks(self, concept_id: str, domain: str) -> list:
        """Use Ollama to synthesise 3 educational paragraphs for the concept."""
        prompt = (
            f"Generate 3 detailed educational paragraphs about '{concept_id}' "
            f"in the domain '{domain}'. "
            "Each paragraph should stand alone as a learning unit."
        )
        try:
            messages = [
                SystemMessage(content="You are an expert educational content generator."),
                HumanMessage(content=prompt),
            ]
            response = self._llm.invoke(messages)
            raw = response.content
            paragraphs = [p.strip() for p in raw.split("\n\n") if p.strip()]
            return paragraphs[:3] if len(paragraphs) >= 3 else (paragraphs or [raw])
        except Exception as exc:
            return [f"[Supplementary content unavailable: {exc}]"]

    def run(self, state: dict) -> dict:
        """Retrieve or generate supplementary chunks and append to lesson_content.

        Args:
            state: GraphState dict with concept_id and domain set.

        Returns:
            Updated state with relevant chunks appended to lesson_content.
        """
        concept_id: str = state.get("concept_id", "unknown")
        domain: str = state.get("domain", "general")

        if not collection_exists(concept_id):
            chunks = self._generate_chunks(concept_id, domain)
            add_documents(concept_id, domain, chunks)

        query = state.get("student_response", concept_id)
        top_chunks = query_documents(concept_id, domain, query, n_results=2)

        if top_chunks:
            supplement = "\n\n--- Additional Context ---\n" + "\n\n".join(top_chunks)
            state["lesson_content"] = state.get("lesson_content", "") + supplement

        return state
