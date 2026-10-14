"""SAE Social Server — the one piece of shared infrastructure in an
otherwise fully local-first system.

Scope is deliberately narrow: accounts, friendships, and messages only.
No lesson content, no AI calls, no test results, no knowledge-graph data —
none of that ever leaves a student's own machine. See sae_system's
SovereigntyError checks (agents/tutor_agent.py, agents/roadmap_agent.py,
etc.) for the guarantee this server does not and must not touch.
"""

from fastapi import FastAPI

from app.routers import accounts, friends, messages

app = FastAPI(
    title="SAE Social Server",
    description="Friend requests, presence, and messaging for SAE System students.",
    version="0.1.0",
)

app.include_router(accounts.router)
app.include_router(friends.router)
app.include_router(messages.router)


@app.get("/health")
def health():
    return {"status": "ok"}
