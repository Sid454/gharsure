"""Rental safety assistant: retrieval over a curated knowledge base (RAG retrieval step).

Answers are returned verbatim from trusted sections with their source title, so the
assistant cannot hallucinate. An LLM can later be added on top to rephrase the
retrieved passages (the 'generation' step).
"""
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .db import ROOT

KB_PATH = ROOT / "data" / "seed" / "knowledge.md"


class Assistant:
    def __init__(self):
        text = KB_PATH.read_text(encoding="utf-8")
        self.sections = []
        for block in re.split(r"^## ", text, flags=re.M):
            if block.strip():
                title, _, body = block.partition("\n")
                self.sections.append({"title": title.strip(), "body": body.strip()})
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
        self.matrix = self.vectorizer.fit_transform(f"{s['title']} {s['title']} {s['body']}" for s in self.sections)

    def ask(self, question: str, k: int = 2) -> dict:
        sims = cosine_similarity(self.vectorizer.transform([question]), self.matrix)[0]
        ranked = sims.argsort()[::-1][:k]
        hits = [{**self.sections[i], "score": round(float(sims[i]), 3)} for i in ranked if sims[i] > 0.05]
        if not hits:
            return {"answer": "I don't have verified information on that yet. General rule: never pay before "
                              "visiting the flat and signing an agreement.", "sources": []}
        return {"answer": hits[0]["body"], "sources": [{"title": h["title"], "score": h["score"]} for h in hits]}
