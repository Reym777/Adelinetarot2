"""Public article feed + admin article publishing endpoints."""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from html import escape as html_escape
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..article_backup import delete_draft_snapshot, push_articles_snapshot, push_draft_snapshot
from ..database import get_db
from ..mailer import send_article_copy_to_contact
from ..models import Article
from ..schemas import ArticleCreate, ArticleDetail, ArticleDraftSave, ArticleEmailRequest, ArticleImport, ArticleSummary, ArticleTranslation
from ..security import read_rate_limit, require_admin, write_rate_limit

router = APIRouter(prefix="/api/articles", tags=["articles"])

_TEXT_TRANSLATION_CACHE: Dict[Tuple[str, str], str] = {}
_ARTICLE_TRANSLATION_CACHE: Dict[Tuple[str, str, datetime], ArticleTranslation] = {}
_TRANSLATION_NOTE = "Traducido por IA"


class _HtmlTranslationParser(HTMLParser):
    def __init__(self, target_lang: str):
        super().__init__(convert_charrefs=False)
        self.target_lang = target_lang
        self.parts: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        self.parts.append("<" + tag)
        for name, value in attrs:
            if value is None:
                self.parts.append(f" {name}")
            else:
                self.parts.append(f' {name}="{html_escape(value, quote=True)}"')
        self.parts.append(">")

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(f"</{tag}>")

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.parts.append("<" + tag)
        for name, value in attrs:
            if value is None:
                self.parts.append(f" {name}")
            else:
                self.parts.append(f' {name}="{html_escape(value, quote=True)}"')
        self.parts.append(" />")

    def handle_data(self, data: str) -> None:
        self.parts.append(_translate_preserving_whitespace(data, self.target_lang))

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.parts.append(f"<!--{data}-->")

    def translated_html(self) -> str:
        return "".join(self.parts)


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


def _strip_markdown(md: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^\)]*\)", "", md)
    text = re.sub(r"\[[^\]]+\]\([^\)]*\)", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[`#>*_~\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _translate_text(text: str, target_lang: str) -> str:
    clean_text = str(text or "")
    if not clean_text.strip():
        return clean_text

    cache_key = (target_lang, clean_text)
    cached = _TEXT_TRANSLATION_CACHE.get(cache_key)
    if cached is not None:
        return cached

    query = urlencode(
        [
            ("client", "gtx"),
            ("sl", "es"),
            ("tl", target_lang),
            ("dt", "t"),
            ("q", clean_text),
        ],
        doseq=True,
    )
    request = Request(
        url=f"https://translate.googleapis.com/translate_a/single?{query}",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))

    translated = "".join(part[0] for part in payload[0] if part and part[0])
    _TEXT_TRANSLATION_CACHE[cache_key] = translated
    return translated


def _translate_preserving_whitespace(text: str, target_lang: str) -> str:
    if not text or not text.strip():
        return text

    leading = re.match(r"^\s*", text).group(0)
    trailing = re.search(r"\s*$", text).group(0)
    core = text.strip()
    return f"{leading}{_translate_text(core, target_lang)}{trailing}"


def _translate_markdown_line(line: str, target_lang: str) -> str:
    if not line.strip():
        return line

    image_match = re.match(r"^(\s*!\[[^\]]*\]\([^\)]+\))(.*)$", line)
    if image_match:
        tail = _translate_preserving_whitespace(image_match.group(2), target_lang)
        return f"{image_match.group(1)}{tail}"

    prefix_match = re.match(r"^(\s*(?:#{1,6}|>|-|\*|\+|\d+\.)\s+)(.+)$", line)
    if prefix_match:
        prefix, body = prefix_match.groups()
        return prefix + _translate_text(body, target_lang)

    return _translate_preserving_whitespace(line, target_lang)


def _translate_content(content: str, target_lang: str) -> str:
    raw = str(content or "")
    if not raw.strip():
        return raw

    if re.search(r"<\s*[a-zA-Z][^>]*>", raw):
        parser = _HtmlTranslationParser(target_lang)
        parser.feed(raw)
        parser.close()
        return parser.translated_html()

    return "\n".join(_translate_markdown_line(line, target_lang) for line in raw.splitlines())


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


def _translate_article(row: Article, target_lang: str) -> ArticleTranslation:
    cache_key = (row.slug, target_lang, row.updated_at)
    cached = _ARTICLE_TRANSLATION_CACHE.get(cache_key)
    if cached is not None:
        return cached

    translated = ArticleTranslation(
        slug=row.slug,
        title=_translate_text(row.title, target_lang),
        subtitle=_translate_text(row.subtitle, target_lang) if row.subtitle else None,
        excerpt=_translate_text(row.excerpt, target_lang) if row.excerpt else None,
        hero_image=row.hero_image,
        author_name=row.author_name,
        created_at=row.created_at,
        content=_translate_content(row.content, target_lang),
        language=target_lang,
        translation_note=_TRANSLATION_NOTE,
    )
    _ARTICLE_TRANSLATION_CACHE[cache_key] = translated
    return translated


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
            is_published=int(payload.is_published or 1),
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
        row.is_published = int(payload.is_published or 1)
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

    row.is_published = 1
    row.updated_at = datetime.now(timezone.utc)
    if not row.excerpt:
        row.excerpt = plain[:220] or None
    db.commit()
    db.refresh(row)
    push_articles_snapshot(db, reason=f"publish-draft:{slug}")
    delete_draft_snapshot(slug, reason="published")
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


@router.get("/{slug}/translation", response_model=ArticleTranslation)
def article_translation_route(
    slug: str,
    lang: str = "en",
    _: None = Depends(read_rate_limit),
    db: Session = Depends(get_db),
) -> ArticleTranslation:
    target_lang = (lang or "").strip().lower()
    if target_lang != "en":
        raise HTTPException(status_code=422, detail="Solo se admite traduccion automatica al ingles")

    row = _published_article_or_404(db, slug)
    try:
        return _translate_article(row, target_lang)
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
