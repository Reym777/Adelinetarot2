"""Fast, cached ES -> EN/FR translation (batched, parallel, persistent)."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from .models import TranslationCache

logger = logging.getLogger("adelinemagica.translation")

_HOSTS = (
    "https://translate.googleapis.com/translate_a/single",
    "https://translate.google.com/translate_a/single",
)
_MAX_BATCH_CHARS = 3800
_MAX_BATCH_SEGMENTS = 80
_MAX_WORKERS = 6
_RETRIES = 3
_MEM_CACHE: Dict[str, str] = {}
_MEM_LOCK = threading.Lock()
_MEM_LIMIT = 20000
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;:])\s+")


def _key(lang: str, text: str) -> str:
    return hashlib.sha1(f"{lang}\0{text}".encode("utf-8")).hexdigest()


def _post(text: str, lang: str, timeout: float = 20.0) -> str:
    last_error: Optional[Exception] = None
    params = urlencode([("client", "gtx"), ("sl", "es"), ("tl", lang), ("dt", "t")])
    body = urlencode({"q": text}).encode("utf-8")
    for attempt in range(_RETRIES):
        host = _HOSTS[attempt % len(_HOSTS)]
        request = Request(
            url=f"{host}?{params}",
            data=body,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            translated = "".join(part[0] for part in payload[0] if part and part[0])
            if translated.strip():
                return translated
            raise ValueError("empty translation")
        except Exception as exc:
            last_error = exc
            time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"translation failed: {last_error}")


def _split_long(text: str) -> List[str]:
    if len(text) <= _MAX_BATCH_CHARS - 300:
        return [text]
    pieces: List[str] = []
    current = ""
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        while len(sentence) > _MAX_BATCH_CHARS - 300:
            cut = sentence.rfind(" ", 0, _MAX_BATCH_CHARS - 300)
            cut = cut if cut > 0 else _MAX_BATCH_CHARS - 300
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut])
            sentence = sentence[cut:].lstrip()
        if current and len(current) + len(sentence) + 1 > _MAX_BATCH_CHARS - 300:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def _translate_batch(texts: List[str], lang: str) -> List[str]:
    if len(texts) == 1:
        return [_post(texts[0], lang)]
    joined = "\n".join(texts)
    try:
        out = _post(joined, lang).split("\n")
        if len(out) == len(texts) and all(item.strip() for item in out):
            return [item.strip() for item in out]
    except Exception:
        logger.warning("Batch translation failed, falling back per segment", exc_info=True)
    return [_post(text, lang) for text in texts]


def _pack(texts: List[str]) -> List[List[int]]:
    batches: List[List[int]] = []
    current: List[int] = []
    size = 0
    for idx, text in enumerate(texts):
        if current and (size + len(text) + 1 > _MAX_BATCH_CHARS or len(current) >= _MAX_BATCH_SEGMENTS):
            batches.append(current)
            current, size = [], 0
        current.append(idx)
        size += len(text) + 1
    if current:
        batches.append(current)
    return batches


def _mem_get(key: str) -> Optional[str]:
    with _MEM_LOCK:
        return _MEM_CACHE.get(key)


def _mem_set(key: str, value: str) -> None:
    with _MEM_LOCK:
        if len(_MEM_CACHE) >= _MEM_LIMIT:
            _MEM_CACHE.clear()
        _MEM_CACHE[key] = value


def translate_segments(db: Session, segments: List[str], lang: str) -> List[str]:
    """Translate each segment (single-line text); preserves order and length."""
    results: List[Optional[str]] = [None] * len(segments)
    passthrough = set()
    unique: Dict[str, List[int]] = {}
    for idx, seg in enumerate(segments):
        text = re.sub(r"\s+", " ", (seg or "").strip())
        if not text or not _LETTER_RE.search(text):
            passthrough.add(idx)
            continue
        unique.setdefault(text, []).append(idx)

    pending: List[str] = []
    keys: Dict[str, str] = {}
    for text in unique:
        k = _key(lang, text)
        keys[text] = k
        cached = _mem_get(k)
        if cached is not None:
            for idx in unique[text]:
                results[idx] = cached
        else:
            pending.append(text)

    if pending:
        rows = (
            db.query(TranslationCache.key, TranslationCache.text)
            .filter(TranslationCache.key.in_([keys[t] for t in pending]))
            .all()
        )
        stored = {row[0]: row[1] for row in rows}
        still: List[str] = []
        for text in pending:
            value = stored.get(keys[text])
            if value is None:
                still.append(text)
                continue
            _mem_set(keys[text], value)
            for idx in unique[text]:
                results[idx] = value
        pending = still

    if pending:
        pieces: List[str] = []
        owner: List[int] = []
        for t_idx, text in enumerate(pending):
            for piece in _split_long(text):
                pieces.append(piece)
                owner.append(t_idx)
        batches = _pack(pieces)
        translated_pieces: List[Optional[str]] = [None] * len(pieces)

        def run(batch: List[int]) -> None:
            out = _translate_batch([pieces[i] for i in batch], lang)
            for i, value in zip(batch, out):
                translated_pieces[i] = value

        if len(batches) == 1:
            run(batches[0])
        else:
            with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(batches))) as pool:
                for future in [pool.submit(run, b) for b in batches]:
                    future.result()

        joined: Dict[int, List[str]] = {}
        for piece_idx, t_idx in enumerate(owner):
            joined.setdefault(t_idx, []).append(translated_pieces[piece_idx] or pieces[piece_idx])

        for t_idx, text in enumerate(pending):
            value = " ".join(joined[t_idx]).strip()
            k = keys[text]
            _mem_set(k, value)
            db.merge(TranslationCache(key=k, lang=lang, text=value))
            for idx in unique[text]:
                results[idx] = value
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("Could not persist translation cache", exc_info=True)

    out_list: List[str] = []
    for idx, seg in enumerate(segments):
        value = results[idx]
        if idx in passthrough or value is None:
            out_list.append(seg)
            continue
        lead = re.match(r"^\s*", seg).group(0)
        trail = re.search(r"\s*$", seg).group(0)
        out_list.append(f"{lead}{value.strip()}{trail}")
    return out_list
