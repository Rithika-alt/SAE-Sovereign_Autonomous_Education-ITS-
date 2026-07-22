"""StressReliefManager: Ollama-powered curiosity cards for the Recharge page."""

import os
from typing import List

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from agents.tutor_agent import SovereigntyError


class StressReliefManager:
    """Generates curiosity / fun-fact cards via local Ollama."""

    def __init__(self) -> None:
        base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        model: str = os.getenv("OLLAMA_MODEL", "llama3.2")
        if not (
            base_url.startswith("http://localhost")
            or base_url.startswith("http://127.0.0.1")
        ):
            raise SovereigntyError(f"OLLAMA_BASE_URL '{base_url}' is not localhost.")
        self._llm = ChatOllama(model=model, base_url=base_url, temperature=0.85)

    def get_curiosity_card(
        self,
        domain: str,
        concept: str,
        shown_facts: List[str],
    ) -> str:
        """Return a short, surprising fun-fact about concept in domain.

        Args:
            domain:      Subject domain (e.g. "Machine Learning").
            concept:     Current concept the student is studying.
            shown_facts: Previously shown facts to avoid repetition.

        Returns:
            A 1-3 sentence curiosity card string.
        """
        exclusions = ""
        if shown_facts:
            bullets = "\n".join(f"- {f[:80]}" for f in shown_facts[-5:])
            exclusions = f"\n\nAvoid repeating these already-shown facts:\n{bullets}"

        system = (
            "You are a curious, enthusiastic professor who loves sharing "
            "mind-blowing facts with stressed students. Keep it brief (2-3 sentences), "
            "surprising, and conversational. No markdown. No bullet points."
        )
        prompt = (
            f"Give me one surprising, delightful fun-fact about '{concept}' "
            f"in the context of {domain}. Make it feel like a 'whoa, I never knew that!' moment."
            f"{exclusions}"
        )
        try:
            resp = self._llm.invoke([
                SystemMessage(content=system),
                HumanMessage(content=prompt),
            ])
            text = resp.content.strip()
            # Trim to 3 sentences max
            sentences = text.replace("! ", "!|").replace(". ", ".|").replace("? ", "?|").split("|")
            return " ".join(s.strip() for s in sentences[:3] if s.strip())
        except Exception:
            return (
                f"Did you know that '{concept}' in {domain} has surprised even seasoned "
                "researchers? Take a breath — you're doing great. Curiosity is the engine of learning."
            )
