"""Scam text classifier (TF-IDF + Logistic Regression) plus explainable red-flag rules."""
import csv
import pickle
import re
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from .db import DATA_DIR, ROOT

SEED_CSV = ROOT / "data" / "seed" / "scam_texts.csv"
MODEL_PATH = DATA_DIR / "models" / "scam_text.pkl"

# Hand-written rules: each one is a known scam pattern with a human-readable reason.
RED_FLAGS = [
    (r"\b(army|crpf|bsf|defen[cs]e|military|officer)\b", "Claims to be army/defence personnel (common scam story)"),
    (r"\b(abroad|dubai|usa|out of (station|city)|bahar)\b", "Owner says they are away and cannot meet"),
    (r"\b(courier|deliver(y)?)\b.*\b(key|keys|chabi)\b|\b(key|keys|chabi)\b.*\b(courier)\b", "Offers to courier the keys"),
    (r"\b(no|not|nahi|without)\b.{0,25}\b(visit|dekh|meet|meeting|agreement)\b|visit not (possible|allowed)|without seeing", "Avoids a visit or written agreement"),
    (r"\b(token|advance|booking amount|deposit|payment|bhej)\b.{0,40}\b(first|pehle|before|today|now|abhi|jaldi)\b|\b(pehle|first)\b.{0,30}\b(advance|deposit|token)\b", "Asks for money before you see the flat"),
    (r"\b(urgent(ly)?|hurry|jaldi|last \d* ?flat|only today|within \d+ hour|many people waiting|warna)\b", "Creates urgency / pressure to pay quickly"),
    (r"\b(otp)\b", "Asks for an OTP (never share OTPs)"),
    (r"\b(qr code|collect request|scan)\b", "Asks you to scan a QR / accept a collect request (this sends money OUT)"),
    (r"\b(registration fee|entry fee|documentation charges|gate pass|verification charges|broker fee)\b", "Charges a fee just to see the flat"),
    (r"\b(trust me|don'?t tell anyone|special discount only for you)\b", "Emotional manipulation / secrecy"),
]


def red_flags(text: str) -> list[str]:
    t = text.lower()
    return [reason for pattern, reason in RED_FLAGS if re.search(pattern, t)]


class ScamTextModel:
    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline

    @classmethod
    def train(cls, csv_path: Path = SEED_CSV) -> "ScamTextModel":
        texts, labels = [], []
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                texts.append(row["text"])
                labels.append(int(row["label"]))
        pipe = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1, lowercase=True)),
            ("clf", LogisticRegression(C=4.0, max_iter=2000, class_weight="balanced")),
        ])
        pipe.fit(texts, labels)
        return cls(pipe)

    def save(self, path: Path = MODEL_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self.pipeline, f)

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "ScamTextModel":
        with open(path, "rb") as f:
            return cls(pickle.load(f))  # noqa: S301 - our own model file

    def predict(self, text: str) -> dict:
        """Scam probability plus the words that pushed the score up (explainability)."""
        if not text.strip():
            return {"probability": 0.0, "top_terms": []}
        prob = float(self.pipeline.predict_proba([text])[0][1])
        tfidf = self.pipeline.named_steps["tfidf"]
        coef = self.pipeline.named_steps["clf"].coef_[0]
        vec = tfidf.transform([text]).toarray()[0]
        contrib = vec * coef
        terms = tfidf.get_feature_names_out()
        top = [terms[i] for i in np.argsort(contrib)[::-1][:5] if contrib[i] > 0.05]
        return {"probability": round(prob, 3), "top_terms": top}
