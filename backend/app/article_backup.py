"""Durable article backup/restore via GitHub Contents API."""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, parse, request

from sqlalchemy.orm import Session

from .config import settings
from .models import Article

logger = logging.getLogger("adelinemagica")


def _github_api_url() -> str:
    repo = settings.articles_backup_github_repo.strip()
    path = settings.articles_backup_github_path.strip().lstrip("/")
    branch = settings.articles_backup_github_branch.strip() or "main"
    return (
        "https://api.github.com/repos/"
        f"{repo}/contents/{parse.quote(path)}?ref={parse.quote(branch)}"
    )


def _github_headers() -> Dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {settings.articles_backup_github_token.strip()}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "adelinemagica-backend",
    }


def _request_json(url: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url=url, method=method, data=data, headers=_github_headers())
    with request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}


def _parse_dt(value: Any) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _article_to_dict(row: Article) -> Dict[str, Any]:
    return {
        "slug": row.slug,
        "title": row.title,
        "subtitle": row.subtitle,
        "hero_image": row.hero_image,
        "excerpt": row.excerpt,
        "content": row.content,
        "author_name": row.author_name,
        "is_published": int(row.is_published or 0),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _list_local_articles(db: Session) -> List[Dict[str, Any]]:
    rows = db.query(Article).order_by(Article.created_at.asc(), Article.id.asc()).all()
    return [_article_to_dict(row) for row in rows]


def load_remote_articles() -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if not settings.articles_backup_enabled:
        return [], None

    url = _github_api_url()
    try:
        payload = _request_json(url)
    except error.HTTPError as exc:
        if exc.code == 404:
            return [], None
        logger.warning("GitHub article backup read failed (HTTP %s)", exc.code)
        return [], None
    except Exception:
        logger.warning("GitHub article backup read failed", exc_info=True)
        return [], None

    content_b64 = str(payload.get("content") or "").replace("\n", "")
    if not content_b64:
        return [], payload.get("sha")

    try:
        raw = base64.b64decode(content_b64.encode("ascii")).decode("utf-8")
        data = json.loads(raw)
    except Exception:
        logger.warning("GitHub article backup decode failed", exc_info=True)
        return [], payload.get("sha")

    if isinstance(data, dict):
        data = data.get("articles", [])
    if not isinstance(data, list):
        return [], payload.get("sha")

    valid: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "").strip()
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        if not slug or not title or not content:
            continue
        valid.append(item)
    return valid, payload.get("sha")


def push_articles_snapshot(db: Session, reason: str = "sync") -> bool:
    if not settings.articles_backup_enabled:
        return False

    local_articles = _list_local_articles(db)
    remote_articles, remote_sha = load_remote_articles()

    payload_obj = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "articles": local_articles,
    }
    payload_text = json.dumps(payload_obj, ensure_ascii=False, indent=2)
    content_b64 = base64.b64encode(payload_text.encode("utf-8")).decode("ascii")

    body: Dict[str, Any] = {
        "message": f"chore(articles): backup {reason}",
        "content": content_b64,
        "branch": settings.articles_backup_github_branch.strip() or "main",
    }
    if remote_sha:
        body["sha"] = remote_sha

    try:
        _request_json(_github_api_url(), method="PUT", payload=body)
        logger.info(
            "Article backup pushed to GitHub (%s local, %s remote before)",
            len(local_articles),
            len(remote_articles),
        )
        return True
    except Exception:
        logger.warning("Failed to push article backup to GitHub", exc_info=True)
        return False


def restore_articles_from_backup(db: Session) -> Dict[str, int]:
    """Restore missing/updated articles from GitHub backup into DB."""
    result = {"restored": 0, "updated": 0, "remote": 0}
    if not settings.articles_backup_enabled:
        return result

    remote_articles, _ = load_remote_articles()
    result["remote"] = len(remote_articles)
    if not remote_articles:
        return result

    changed = False
    for item in remote_articles:
        slug = str(item.get("slug") or "").strip()
        row = db.query(Article).filter(Article.slug == slug).first()

        created_at = _parse_dt(item.get("created_at"))
        updated_at = _parse_dt(item.get("updated_at"))
        is_published = int(item.get("is_published") or 0)

        if row is None:
            row = Article(
                slug=slug,
                title=str(item.get("title") or "").strip(),
                subtitle=(str(item.get("subtitle") or "").strip() or None),
                hero_image=(str(item.get("hero_image") or "").strip() or None),
                excerpt=(str(item.get("excerpt") or "").strip() or None),
                content=str(item.get("content") or "").strip(),
                author_name=(str(item.get("author_name") or "Adeline").strip() or "Adeline"),
                is_published=is_published,
                created_at=created_at,
                updated_at=updated_at,
            )
            db.add(row)
            result["restored"] += 1
            changed = True
            continue

        incoming_updated_at = updated_at
        current_updated_at = row.updated_at or datetime.fromtimestamp(0, tz=timezone.utc)
        if current_updated_at.tzinfo is None:
            current_updated_at = current_updated_at.replace(tzinfo=timezone.utc)
        if incoming_updated_at > current_updated_at:
            row.title = str(item.get("title") or row.title).strip() or row.title
            row.subtitle = (str(item.get("subtitle") or "").strip() or None)
            row.hero_image = (str(item.get("hero_image") or "").strip() or None)
            row.excerpt = (str(item.get("excerpt") or "").strip() or None)
            row.content = str(item.get("content") or row.content).strip() or row.content
            row.author_name = (str(item.get("author_name") or row.author_name).strip() or row.author_name)
            row.is_published = is_published
            row.updated_at = incoming_updated_at
            result["updated"] += 1
            changed = True

    if changed:
        db.commit()
    return result
