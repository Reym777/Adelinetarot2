"""Public article feed + admin article publishing endpoints."""
from __future__ import annotations

import logging
import re
import threading
import unicodedata
from datetime import datetime, timezone
from html import escape as html_escape
from html import unescape as html_unescape
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..article_backup import (
    delete_draft_snapshot,
    push_articles_snapshot,
    push_draft_snapshot,
    restore_articles_from_backup,
)
from ..database import get_db
from ..mailer import send_article_copy_to_contact
from ..models import Article, ArticleComment, ArticleLike
from ..schemas import ArticleCommentCreate, ArticleCommentPublic, ArticleCreate, ArticleDetail, ArticleDraftSave, ArticleEmailRequest, ArticleFeedback, ArticleImport, ArticleLikeCreate, ArticleLikeResponse, ArticleSummary, ArticleTranslation, ArticleUpdate
from ..security import read_rate_limit, require_admin, write_rate_limit
from ..translation import translate_segments

logger = logging.getLogger("adelinemagica.articles")
router = APIRouter(prefix="/api/articles", tags=["articles"])

_ARTICLE_TRANSLATION_CACHE: Dict[Tuple[str, str, datetime], ArticleTranslation] = {}
_TRANSLATION_NOTE = "Traducido por IA"


class _HtmlSegmentParser(HTMLParser):
    """Splits HTML into literal markup and translatable text runs."""

    _SKIP_TAGS = ("script", "style")

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.tokens: List[Tuple[bool, str]] = []
        self._run: List[str] = []
        self._skip_depth = 0

    def _flush(self) -> None:
        if self._run:
            raw = "".join(self._run)
            self._run = []
            self.tokens.append((self._skip_depth == 0, raw))

    def _literal(self, text: str) -> None:
        self._flush()
        self.tokens.append((False, text))

    def _tag_html(self, tag: str, attrs, closing: str) -> str:
        parts = ["<" + tag]
        for name, value in attrs:
            if value is None:
                parts.append(f" {name}")
            else:
                parts.append(f' {name}="{html_escape(value, quote=True)}"')
        parts.append(closing)
        return "".join(parts)

    def handle_starttag(self, tag: str, attrs) -> None:
        self._literal(self._tag_html(tag, attrs, ">"))
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        self._literal(f"</{tag}>")
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_startendtag(self, tag: str, attrs) -> None:
        self._literal(self._tag_html(tag, attrs, " />"))

    def handle_data(self, data: str) -> None:
        self._run.append(data)

    def handle_entityref(self, name: str) -> None:
        self._run.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._run.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._literal(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self._literal(f"<!{decl}>")

    def close(self) -> None:
        super().close()
        self._flush()


def _slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:200] or "articulo"


def _make_unique_slug(db: Session, title: str) -> str:
    base = _slugify(title)
    slug = base
    idx = 2
    while db.query(Article).filter(Article.slug == slug).first() is not None:
        suffix = f"-{idx}"
        slug = (base[: 200 - len(suffix)] + suffix).strip("-")
        idx += 1
    return slug


def _rename_article_slug(db: Session, row: Article, new_slug: str) -> None:
    old_slug = row.slug
    row.slug = new_slug
    db.flush()
    db.query(ArticleComment).filter(ArticleComment.article_slug == old_slug).update(
        {ArticleComment.article_slug: new_slug}, synchronize_session=False
    )
    db.query(ArticleLike).filter(ArticleLike.article_slug == old_slug).update(
        {ArticleLike.article_slug: new_slug}, synchronize_session=False
    )


def normalize_article_slugs(db: Session) -> int:
    changed = 0
    rows = db.query(Article).order_by(Article.id.asc()).all()
    for row in rows:
        base = _slugify(row.title or "")
        if row.slug == base or re.fullmatch(re.escape(base) + r"-\d+", row.slug or ""):
            continue
        target = base
        idx = 2
        while db.query(Article).filter(Article.slug == target, Article.id != row.id).first() is not None:
            suffix = f"-{idx}"
            target = (base[: 200 - len(suffix)] + suffix).strip("-")
            idx += 1
        _rename_article_slug(db, row, target)
        changed += 1
    if changed:
        db.commit()
        push_articles_snapshot(db, reason="normalize-slugs")
    return changed


def _strip_markdown(md: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^\)]*\)", "", md)
    text = re.sub(r"\[[^\]]+\]\([^\)]*\)", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[`#>*_~\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _translate_content(db: Session, content: str, target_lang: str, extra: Optional[List[str]] = None) -> Tuple[str, List[str]]:
    """Translate content plus extra standalone strings in one batched pass."""
    extra = extra or []
    raw = str(content or "")
    segments: List[str] = list(extra)
    layout: List[Tuple[str, object]] = []

    if raw.strip() and re.search(r"<\s*[a-zA-Z][^>]*>", raw):
        parser = _HtmlSegmentParser()
        parser.feed(raw)
        parser.close()
        for translatable, text in parser.tokens:
            if translatable and text.strip():
                layout.append(("seg", len(segments)))
                segments.append(html_unescape(text))
            else:
                layout.append(("lit", text))
        html_mode = True
    else:
        html_mode = False
        for line in raw.splitlines():
            if not line.strip():
                layout.append(("lit", line))
                layout.append(("nl", "\n"))
                continue
            image_match = re.match(r"^(\s*!\[[^\]]*\]\([^\)]+\))(.*)$", line)
            prefix_match = re.match(r"^(\s*(?:#{1,6}|>|-|\*|\+|\d+\.)\s+)(.+)$", line)
            if image_match:
                prefix, body = image_match.groups()
            elif prefix_match:
                prefix, body = prefix_match.groups()
            else:
                prefix, body = "", line
            layout.append(("lit", prefix))
            layout.append(("seg", len(segments)))
            layout.append(("nl", "\n"))
            segments.append(body)

    translated = translate_segments(db, segments, target_lang)

    out: List[str] = []
    for kind, value in layout:
        if kind == "seg":
            text = translated[value]  # type: ignore[index]
            out.append(html_escape(text, quote=False) if html_mode else text)
        else:
            out.append(str(value))
    if html_mode:
        return "".join(out), translated[: len(extra)]
    joined = "".join(out)
    if joined.endswith("\n"):
        joined = joined[:-1]
    return joined, translated[: len(extra)]


def _published_article_or_404(db: Session, slug: str) -> Article:
    row = (
        db.query(Article)
        .filter(Article.slug == slug)
        .filter(Article.is_published == 1)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Articulo no encontrado")
    return row


def _translate_article(db: Session, row: Article, target_lang: str) -> ArticleTranslation:
    cache_key = (row.slug, target_lang, row.updated_at)
    cached = _ARTICLE_TRANSLATION_CACHE.get(cache_key)
    if cached is not None:
        return cached

    extra = [row.title or "", row.subtitle or "", row.excerpt or ""]
    content, (title, subtitle, excerpt) = _translate_content(db, row.content, target_lang, extra)
    translated = ArticleTranslation(
        slug=row.slug,
        title=title,
        subtitle=subtitle if row.subtitle else None,
        excerpt=excerpt if row.excerpt else None,
        hero_image=row.hero_image,
        author_name=row.author_name,
        created_at=row.created_at,
        content=content,
        language=target_lang,
        translation_note=_TRANSLATION_NOTE,
    )
    if len(_ARTICLE_TRANSLATION_CACHE) > 200:
        _ARTICLE_TRANSLATION_CACHE.clear()
    _ARTICLE_TRANSLATION_CACHE[cache_key] = translated
    return translated


def warm_translations() -> None:
    """Pre-translate every published article so readers get instant results."""
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        rows = db.query(Article).filter(Article.is_published == 1).all()
        for row in rows:
            for lang in ("en", "fr"):
                try:
                    _translate_article(db, row, lang)
                except Exception:
                    logger.warning("Translation warm-up failed (%s, %s)", row.slug, lang, exc_info=True)
    finally:
        db.close()


def warm_article_async(slug: str) -> None:
    def work() -> None:
        from ..database import SessionLocal

        db = SessionLocal()
        try:
            row = db.query(Article).filter(Article.slug == slug, Article.is_published == 1).first()
            if row is None:
                return
            for lang in ("en", "fr"):
                try:
                    _translate_article(db, row, lang)
                except Exception:
                    logger.warning("Translation warm-up failed (%s, %s)", slug, lang, exc_info=True)
        finally:
            db.close()

    threading.Thread(target=work, daemon=True).start()



def _summary_from_row(row: Article) -> ArticleSummary:
    return ArticleSummary(
        slug=row.slug,
        title=row.title,
        subtitle=row.subtitle,
        excerpt=row.excerpt,
        hero_image=row.hero_image,
        author_name=row.author_name,
        created_at=row.created_at,
    )


@router.get("", response_model=List[ArticleSummary])
def list_articles(
    _: None = Depends(read_rate_limit),
    db: Session = Depends(get_db),
) -> List[ArticleSummary]:
    rows = (
        db.query(Article)
        .filter(Article.is_published == 1)
        .order_by(Article.created_at.desc())
        .limit(100)
        .all()
    )
    return [_summary_from_row(row) for row in rows]


@router.post("/admin/restore-backup", dependencies=[Depends(require_admin)])
def restore_backup(db: Session = Depends(get_db)) -> Dict[str, int]:
    """Pull missing/updated articles from the GitHub backup into the live DB."""
    return restore_articles_from_backup(db)


@router.get("/admin/export", response_model=List[ArticleDetail], dependencies=[Depends(require_admin)])
def export_articles(
    _: None = Depends(read_rate_limit),
    db: Session = Depends(get_db),
) -> List[ArticleDetail]:
    rows = (
        db.query(Article)
        .order_by(Article.created_at.desc(), Article.id.desc())
        .limit(500)
        .all()
    )
    return [
        ArticleDetail(
            slug=row.slug,
            title=row.title,
            subtitle=row.subtitle,
            excerpt=row.excerpt,
            hero_image=row.hero_image,
            author_name=row.author_name,
            created_at=row.created_at,
            content=row.content,
        )
        for row in rows
    ]


@router.post("/admin/import", response_model=ArticleDetail, dependencies=[Depends(require_admin)])
def import_article(
    payload: ArticleImport,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> ArticleDetail:
    now = datetime.now(timezone.utc)
    excerpt: Optional[str] = payload.excerpt
    if not excerpt:
        excerpt = _strip_markdown(payload.content)[:220]

    requested_slug = _slugify(payload.slug or payload.title)
    row = db.query(Article).filter(Article.slug == requested_slug).first()

    if row is None:
        slug = requested_slug
        existing = db.query(Article).filter(Article.slug == slug).first()
        if existing is not None:
            slug = _make_unique_slug(db, payload.title)

        row = Article(
            slug=slug,
            title=payload.title,
            subtitle=payload.subtitle,
            hero_image=payload.hero_image,
            excerpt=excerpt,
            content=payload.content,
            author_name=(payload.author_name or "Adeline"),
            is_published=int(payload.is_published if payload.is_published is not None else 1),
            created_at=payload.created_at or now,
            updated_at=payload.updated_at or now,
        )
        db.add(row)
    else:
        row.title = payload.title
        row.subtitle = payload.subtitle
        row.hero_image = payload.hero_image
        row.excerpt = excerpt
        row.content = payload.content
        row.author_name = payload.author_name or row.author_name
        row.is_published = int(payload.is_published if payload.is_published is not None else 1)
        row.updated_at = payload.updated_at or now

    db.commit()
    db.refresh(row)
    push_articles_snapshot(db, reason=f"import:{row.slug}")
    return ArticleDetail(
        slug=row.slug,
        title=row.title,
        subtitle=row.subtitle,
        excerpt=row.excerpt,
        hero_image=row.hero_image,
        author_name=row.author_name,
        created_at=row.created_at,
        content=row.content,
    )


@router.get("/admin/drafts", response_model=List[ArticleSummary], dependencies=[Depends(require_admin)])
def list_drafts(
    _: None = Depends(read_rate_limit),
    db: Session = Depends(get_db),
) -> List[ArticleSummary]:
    rows = (
        db.query(Article)
        .filter(Article.is_published == 0)
        .order_by(Article.updated_at.desc(), Article.created_at.desc())
        .limit(100)
        .all()
    )
    return [_summary_from_row(row) for row in rows]


@router.post("/admin/draft", response_model=ArticleDetail, dependencies=[Depends(require_admin)])
def save_draft(
    payload: ArticleDraftSave,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> ArticleDetail:
    now = datetime.now(timezone.utc)
    clean_title = str(payload.title or "").strip() or "Borrador"
    clean_content = str(payload.content or "").strip() or "<p></p>"
    requested_slug = _slugify(payload.slug or clean_title)

    row = None
    if payload.slug:
        row = db.query(Article).filter(Article.slug == payload.slug).first()
        if row is not None and row.is_published == 1:
            row = None

    if row is None:
        slug = requested_slug
        existing = db.query(Article).filter(Article.slug == slug).first()
        if existing is not None:
            slug = _make_unique_slug(db, clean_title)

        row = Article(
            slug=slug,
            title=clean_title,
            subtitle=None,
            hero_image=None,
            excerpt=_strip_markdown(clean_content)[:220] or None,
            content=clean_content,
            author_name="Adeline",
            is_published=0,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.title = clean_title
        row.content = clean_content
        row.excerpt = _strip_markdown(clean_content)[:220] or None
        row.updated_at = now
        row.is_published = 0

    db.commit()
    db.refresh(row)
    push_articles_snapshot(db, reason=f"draft:{row.slug}")
    push_draft_snapshot(row, reason=f"draft:{row.slug}")
    return ArticleDetail(
        slug=row.slug,
        title=row.title,
        subtitle=row.subtitle,
        excerpt=row.excerpt,
        hero_image=row.hero_image,
        author_name=row.author_name,
        created_at=row.created_at,
        content=row.content,
    )


@router.post("/admin/draft/{slug}/publish", response_model=ArticleDetail, dependencies=[Depends(require_admin)])
def publish_draft(
    slug: str,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> ArticleDetail:
    row = db.query(Article).filter(Article.slug == slug).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Borrador no encontrado")
    if row.is_published == 1:
        return ArticleDetail(
            slug=row.slug,
            title=row.title,
            subtitle=row.subtitle,
            excerpt=row.excerpt,
            hero_image=row.hero_image,
            author_name=row.author_name,
            created_at=row.created_at,
            content=row.content,
        )

    plain = _strip_markdown(row.content or "")
    if len(plain) < 80:
        raise HTTPException(status_code=400, detail="El borrador necesita al menos 80 caracteres para publicarse")

    title_slug = _slugify(row.title or "")
    if row.slug != title_slug and db.query(Article).filter(Article.slug == title_slug).first() is None:
        _rename_article_slug(db, row, title_slug)
    published_at = datetime.now(timezone.utc)
    row.is_published = 1
    row.created_at = published_at
    row.updated_at = published_at
    if not row.excerpt:
        row.excerpt = plain[:220] or None
    db.commit()
    db.refresh(row)
    push_articles_snapshot(db, reason=f"publish-draft:{slug}")
    delete_draft_snapshot(slug, reason="published")
    warm_article_async(row.slug)
    return ArticleDetail(
        slug=row.slug,
        title=row.title,
        subtitle=row.subtitle,
        excerpt=row.excerpt,
        hero_image=row.hero_image,
        author_name=row.author_name,
        created_at=row.created_at,
        content=row.content,
    )


@router.post("/admin/email-copy", dependencies=[Depends(require_admin)])
def email_article_copy(
    payload: ArticleEmailRequest,
    _: None = Depends(write_rate_limit),
) -> dict:
    ok, detail = send_article_copy_to_contact(
        title=payload.title,
        content_html=payload.content,
        slug=payload.slug or "",
    )
    if not ok:
        raise HTTPException(status_code=400, detail=f"No se pudo enviar el correo: {detail}")
    return {"ok": True, "message": "Articulo enviado por correo a contact@adelinemagica.com"}


def article_detail(
    slug: str,
    _: None = Depends(read_rate_limit),
    db: Session = Depends(get_db),
) -> ArticleDetail:
    row = _published_article_or_404(db, slug)
    return ArticleDetail(
        slug=row.slug,
        title=row.title,
        subtitle=row.subtitle,
        excerpt=row.excerpt,
        hero_image=row.hero_image,
        author_name=row.author_name,
        created_at=row.created_at,
        content=row.content,
    )


@router.get("/translations/summaries", response_model=List[ArticleSummary])
def translated_summaries(
    lang: str = "en",
    _: None = Depends(read_rate_limit),
    db: Session = Depends(get_db),
) -> List[ArticleSummary]:
    target_lang = (lang or "").strip().lower()
    if target_lang not in ("en", "fr"):
        raise HTTPException(status_code=422, detail="Solo se admite traduccion automatica al ingles o al frances")
    rows = (
        db.query(Article)
        .filter(Article.is_published == 1)
        .order_by(Article.created_at.desc())
        .limit(100)
        .all()
    )
    segments: List[str] = []
    for row in rows:
        segments.extend([row.title or "", row.subtitle or "", row.excerpt or ""])
    try:
        out = translate_segments(db, segments, target_lang)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudo traducir los articulos") from exc
    result: List[ArticleSummary] = []
    for i, row in enumerate(rows):
        title, subtitle, excerpt = out[i * 3], out[i * 3 + 1], out[i * 3 + 2]
        result.append(
            ArticleSummary(
                slug=row.slug,
                title=title,
                subtitle=subtitle if row.subtitle else None,
                excerpt=excerpt if row.excerpt else None,
                hero_image=row.hero_image,
                author_name=row.author_name,
                created_at=row.created_at,
            )
        )
    return result


@router.get("/{slug}/translation", response_model=ArticleTranslation)
def article_translation_route(
    slug: str,
    lang: str = "en",
    _: None = Depends(read_rate_limit),
    db: Session = Depends(get_db),
) -> ArticleTranslation:
    target_lang = (lang or "").strip().lower()
    if target_lang not in ("en", "fr"):
        raise HTTPException(status_code=422, detail="Solo se admite traduccion automatica al ingles o al frances")

    row = _published_article_or_404(db, slug)
    try:
        return _translate_article(db, row, target_lang)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudo traducir el articulo") from exc


@router.get("/{slug}", response_model=ArticleDetail)
def article_detail_route(
    slug: str,
    _: None = Depends(read_rate_limit),
    db: Session = Depends(get_db),
) -> ArticleDetail:
    return article_detail(slug=slug, db=db)


@router.get("/{slug}/feedback", response_model=ArticleFeedback)
def article_feedback(
    slug: str,
    client_id: Optional[str] = None,
    _: None = Depends(read_rate_limit),
    db: Session = Depends(get_db),
) -> ArticleFeedback:
    _published_article_or_404(db, slug)
    comments = (
        db.query(ArticleComment)
        .filter(ArticleComment.article_slug == slug)
        .order_by(ArticleComment.created_at.desc(), ArticleComment.id.desc())
        .limit(100)
        .all()
    )
    likes_query = db.query(ArticleLike).filter(ArticleLike.article_slug == slug)
    liked = False
    if client_id:
        try:
            from uuid import UUID

            normalized_client_id = str(UUID(client_id))
            liked = likes_query.filter(ArticleLike.client_id == normalized_client_id).first() is not None
        except ValueError:
            raise HTTPException(status_code=422, detail="Identificador de cliente no válido")
    return ArticleFeedback(
        comments=[ArticleCommentPublic(id=row.id, text=row.text, created_at=row.created_at) for row in comments],
        likes=likes_query.count(),
        liked=liked,
    )


@router.post("/{slug}/comments", response_model=ArticleCommentPublic)
def create_article_comment(
    slug: str,
    payload: ArticleCommentCreate,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> ArticleCommentPublic:
    _published_article_or_404(db, slug)
    row = ArticleComment(article_slug=slug, text=payload.text)
    db.add(row)
    db.commit()
    db.refresh(row)
    return ArticleCommentPublic(id=row.id, text=row.text, created_at=row.created_at)


@router.post("/{slug}/likes", response_model=ArticleLikeResponse)
def like_article(
    slug: str,
    payload: ArticleLikeCreate,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> ArticleLikeResponse:
    _published_article_or_404(db, slug)
    client_id = str(payload.client_id)
    existing = (
        db.query(ArticleLike)
        .filter(ArticleLike.article_slug == slug, ArticleLike.client_id == client_id)
        .first()
    )
    if existing is None:
        db.add(ArticleLike(article_slug=slug, client_id=client_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    likes = db.query(ArticleLike).filter(ArticleLike.article_slug == slug)
    return ArticleLikeResponse(likes=likes.count(), liked=True)


@router.delete("/{slug}", dependencies=[Depends(require_admin)])
def delete_article(
    slug: str,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> dict:
    row = db.query(Article).filter(Article.slug == slug).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Articulo no encontrado")

    db.delete(row)
    db.commit()
    push_articles_snapshot(db, reason=f"delete:{slug}")
    delete_draft_snapshot(slug, reason="deleted")
    return {"ok": True, "slug": slug}


@router.post("", response_model=ArticleDetail, dependencies=[Depends(require_admin)])
def create_article(
    payload: ArticleCreate,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> ArticleDetail:
    now = datetime.now(timezone.utc)
    excerpt: Optional[str] = payload.excerpt
    if not excerpt:
        excerpt = _strip_markdown(payload.content)[:220]

    row = Article(
        slug=_make_unique_slug(db, payload.title),
        title=payload.title,
        subtitle=payload.subtitle,
        hero_image=payload.hero_image,
        excerpt=excerpt,
        content=payload.content,
        author_name="Adeline",
        is_published=1,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    push_articles_snapshot(db, reason=f"publish:{row.slug}")
    return ArticleDetail(
        slug=row.slug,
        title=row.title,
        subtitle=row.subtitle,
        excerpt=row.excerpt,
        hero_image=row.hero_image,
        author_name=row.author_name,
        created_at=row.created_at,
        content=row.content,
    )


@router.post("/{slug}/update", response_model=ArticleDetail, dependencies=[Depends(require_admin)])
def update_article(
    slug: str,
    payload: ArticleUpdate,
    _: None = Depends(write_rate_limit),
    db: Session = Depends(get_db),
) -> ArticleDetail:
    row = db.query(Article).filter(Article.slug == slug).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Articulo no encontrado")

    new_slug = _slugify(payload.slug) if payload.slug and payload.slug.strip() else row.slug
    if new_slug != row.slug:
        if db.query(Article).filter(Article.slug == new_slug).first() is not None:
            raise HTTPException(status_code=409, detail="Ese slug ya existe")
        _rename_article_slug(db, row, new_slug)

    excerpt: Optional[str] = payload.excerpt
    if excerpt is None:
        excerpt = _strip_markdown(payload.content)[:220] or row.excerpt

    row.title = payload.title
    row.subtitle = payload.subtitle if payload.subtitle is not None else row.subtitle
    row.hero_image = payload.hero_image if payload.hero_image is not None else row.hero_image
    row.excerpt = excerpt
    row.content = payload.content
    row.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(row)
    push_articles_snapshot(db, reason=f"update:{row.slug}")
    warm_article_async(row.slug)
    return ArticleDetail(
        slug=row.slug,
        title=row.title,
        subtitle=row.subtitle,
        excerpt=row.excerpt,
        hero_image=row.hero_image,
        author_name=row.author_name,
        created_at=row.created_at,
        content=row.content,
    )
