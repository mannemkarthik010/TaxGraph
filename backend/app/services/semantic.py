"""Semantic layer for firm-wide search: latent semantic analysis (LSA) over the packet, computed locally.

A TF-IDF matrix over the packet's narrative objects (documents and their pages, client answers, messages, call
notes, timeline, TaxProof findings, engine diagnostics, household facts) is factorised with a truncated SVD.
Words that keep appearing in the same contexts end up near each other in the reduced space, so a query can reach
an object it shares no words with. Everything else (extracted values, return lines, workpaper decisions) is
folded into the same space. No model, no API, nothing leaves the server: the space is learned from this file
alone, built from the already-masked search text, cached by packet hash and rebuilt only when the packet changes.

`search.rank` blends the cosine similarity from here with BM25 and explains every semantic hit by the words in
the result that sit closest to the query in this space.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

import numpy as np

DIMS = 48            # latent dimensions kept
MIN_DF = 2           # a term seen once carries no co-occurrence signal
MAX_DF_SHARE = 0.25  # nor does a term in a quarter of everything
# Function words BM25 tolerates (its idf discounts them) but which would dominate a small latent space.
FUNCTION = set("you if so when where yes no not have has had we i he she they them his her him us will would can could "
               "should may might also just only some each per vs".split())
_ID = re.compile(r"(qa|msg|tl|ev|d|call)-?\d+")
FIT_KINDS = {"Document", "Page", "Client answer", "Client message", "Call note", "Timeline", "TaxProof finding",
             "Engine diagnostic", "Household"}


def _content(tf: Counter) -> Counter:
    """Words only: no function words, numbers, dates or object ids — they name things, they do not mean them."""
    return Counter({t: c for t, c in tf.items() if t not in FUNCTION and t[0].isalpha() and not _ID.fullmatch(t)})


@dataclass
class Space:
    vocab: dict[str, int]
    idf: np.ndarray          # (V,)
    proj: np.ndarray         # (V, k) right singular vectors: TF-IDF -> latent coordinates
    term_unit: np.ndarray    # (V, k) unit term vectors (V·S), for "which word is closest to the query"
    scale: np.ndarray        # (k,) singular values

    def _vector(self, weights: dict[str, float]) -> np.ndarray | None:
        with np.errstate(all="ignore"):   # Accelerate BLAS on macOS can raise spurious matmul FP warnings
            return self._fold(weights)

    def _fold(self, weights: dict[str, float]) -> np.ndarray | None:
        x = np.zeros(len(self.vocab))
        for t, w in weights.items():
            j = self.vocab.get(t)
            if j is not None:
                x[j] += w * self.idf[j]
        if not x.any():
            return None
        v = x / np.linalg.norm(x) @ self.proj
        nrm = float(np.linalg.norm(v))
        return v / nrm if nrm > 0 else None

    def embed(self, tf: Counter) -> np.ndarray | None:
        """A bag of words as a unit vector in the space, or None when none of its words are in the vocabulary."""
        return self._vector({t: 1 + math.log(c) for t, c in _content(tf).items()})

    def embed_query(self, weighted: dict[str, float]) -> np.ndarray | None:
        """Query terms match vocabulary words they are a prefix of, as in BM25 ("donat" → donation, donated)."""
        out: dict[str, float] = {}
        for t, w in weighted.items():
            if not t[:1].isalpha():
                continue
            words = [t] if t in self.vocab else self._prefixed(t) if len(t) >= 4 else []
            for v in words:
                out[v] = max(out.get(v, 0.0), w)
        return self._vector(out)

    def _prefixed(self, t: str) -> list[str]:
        return [v for v in self.vocab if v.startswith(t)]

    def nearest_terms(self, qv: np.ndarray, tf: Counter, exclude: set[str], k: int = 3) -> list[str]:
        """The words of one result that lie closest to the query in the latent space — the "why" of a semantic hit."""
        ids = [(t, self.vocab[t]) for t in _content(tf) if t in self.vocab and t not in exclude and len(t) >= 3]
        if not ids:
            return []
        q = qv * self.scale
        q /= max(float(np.linalg.norm(q)), 1e-12)
        with np.errstate(all="ignore"):
            sims = self.term_unit[[j for _t, j in ids]] @ q
        best = sorted(zip(sims.tolist(), (t for t, _j in ids)), reverse=True)[:k]
        return [t for s, t in best if s > 0.3]


@dataclass
class Index:
    space: Space
    docs: np.ndarray         # (N, k) unit vectors aligned with the search docs (zero row: nothing known)


    def similarities(self, qv: np.ndarray, extra_tfs: list[Counter]) -> np.ndarray:
        """Cosine of the query to every packet doc, then to `extra_tfs` (live workpaper objects), folded in on the fly."""
        with np.errstate(all="ignore"):
            sims = self.docs @ qv
            return np.concatenate([sims, embed_all(self.space, extra_tfs) @ qv]) if extra_tfs else sims


_CACHE: dict[str, Index] = {}


def build(tfs: list[Counter], dims: int = DIMS) -> Space:
    bags = [_content(tf) for tf in tfs]
    n = len(bags)
    df: Counter = Counter()
    for b in bags:
        df.update(b.keys())
    vocab = {t: i for i, t in enumerate(sorted(t for t, c in df.items() if MIN_DF <= c <= n * MAX_DF_SHARE))}
    idf = np.array([math.log(n / df[t]) for t in vocab])
    x = np.zeros((n, len(vocab)))
    for i, b in enumerate(bags):
        for t, c in b.items():
            j = vocab.get(t)
            if j is not None:
                x[i, j] = (1 + math.log(c)) * idf[j]
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    x /= np.where(norms > 0, norms, 1)
    _u, s, vt = np.linalg.svd(x, full_matrices=False)
    k = min(dims, len(s))
    proj, scale = vt[:k].T, s[:k]
    term_vecs = proj * scale
    term_unit = term_vecs / np.maximum(np.linalg.norm(term_vecs, axis=1, keepdims=True), 1e-12)
    return Space(vocab, idf, proj, term_unit, scale)


def embed_all(space: Space, tfs: list[Counter]) -> np.ndarray:
    out = np.zeros((len(tfs), space.proj.shape[1]))
    for i, tf in enumerate(tfs):
        v = space.embed(tf)
        if v is not None:
            out[i] = v
    return out


def index(key: str, kinds: list[str], tfs: list[Counter]) -> Index:
    """The latent space for one packet (keyed by its hash): fitted on the narrative objects, every object embedded."""
    if key not in _CACHE:
        with np.errstate(all="ignore"):   # Accelerate BLAS on macOS can raise spurious matmul FP warnings
            sp = build([tf for kind, tf in zip(kinds, tfs) if kind in FIT_KINDS])
            _CACHE[key] = Index(sp, embed_all(sp, tfs))
    return _CACHE[key]
