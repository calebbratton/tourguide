"""A toy agent loop."""

from .store import read


def run(question, llm):
    context = read("notes") or ""
    while True:
        reply = llm(question, context)
        if reply.get("done"):
            return reply["answer"]
        context += reply["thought"]
