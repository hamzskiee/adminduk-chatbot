"""HANYA UNTUK UJI TAMPILAN (ADMINDUK_MOCK=1). Tidak memakai model AI.
Retriever memakai pipeline asli (rag_adminduk.IntentRetriever) dengan encoder tiruan (hashing n-gram karakter),
dan 'LLM' tiruan yang menyalin referensi pertama. Jangan dipakai untuk demo ke dosen."""
import time

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

import rag_adminduk as rag


class FakeEncoder:
    def __init__(self):
        self.vec = HashingVectorizer(analyzer="char_wb", ngram_range=(2, 4), n_features=2048, alternate_sign=False)

    def encode(self, texts, normalize_embeddings=True, **_):
        x = self.vec.transform(texts).toarray().astype(np.float32)
        if normalize_embeddings:
            x /= np.linalg.norm(x, axis=1, keepdims=True).clip(min=1e-9)
        return x


class MockAsisten(rag.AsistenAdminduk):
    delay = 1.2  # meniru jeda CPU

    def generate(self, messages):
        time.sleep(self.delay)
        user = messages[-1]["content"]
        first = user.split("\n")[1]          # "[1] topik: jawaban"
        return first.split(": ", 1)[1]


def build(kb, slang, system_prompt, cfg):
    retriever = rag.IntentRetriever(kb, slang, FakeEncoder(), C=cfg["retriever_C"], prefix=cfg["prefix"])
    return MockAsisten(retriever, None, None, system_prompt, [], **cfg["pipeline"])
