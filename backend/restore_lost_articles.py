"""Reimporte les editoriaux perdus (snapshot GitHub du 2026-08-27) dans la base live via /api/articles/admin/import.

Usage:
    $env:ADELINE_ADMIN_TOKEN = "..."   # token admin de production (voir logs Render)
    python restore_lost_articles.py --base-url https://adelinetarot2.onrender.com

borrador-2 et prendele-fuego-a-tu-consciencia sont forces en brouillon (is_published=0):
un bug de /admin/import les avait publies par erreur lors d'une precedente tentative.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

IS_PUBLISHED_OVERRIDES = {
    "borrador-2": 0,
    "prendele-fuego-a-tu-consciencia": 0,
}


def import_article(base_url: str, token: str, article: dict) -> None:
    slug = article["slug"]
    is_published = IS_PUBLISHED_OVERRIDES.get(slug, int(article.get("is_published") or 0))
    payload = {
        "slug": slug,
        "title": article["title"],
        "subtitle": article.get("subtitle"),
        "hero_image": article.get("hero_image"),
        "excerpt": article.get("excerpt"),
        "content": article["content"],
        "author_name": article.get("author_name") or "Adeline",
        "is_published": is_published,
        "created_at": article.get("created_at"),
        "updated_at": article.get("updated_at"),
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=f"{base_url.rstrip('/')}/api/articles/admin/import",
        method="POST",
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Admin-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"OK   {slug} -> HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"FAIL {slug} -> HTTP {exc.code}: {body}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="ex: https://adelinetarot2.onrender.com")
    parser.add_argument(
        "--snapshot",
        default=str(Path(__file__).with_name("recovered_articulos_20260827.json")),
    )
    parser.add_argument(
        "--only",
        help="Liste de slugs (separes par des virgules) a reimporter, au lieu de tous",
    )
    args = parser.parse_args()

    token = os.environ.get("ADELINE_ADMIN_TOKEN", "").strip()
    if not token:
        print("Definir ADELINE_ADMIN_TOKEN dans l'environnement avant de lancer ce script.", file=sys.stderr)
        sys.exit(1)

    data = json.loads(Path(args.snapshot).read_text(encoding="utf-8-sig"))
    articles = data.get("articles") if isinstance(data, dict) else data
    if not isinstance(articles, list):
        print("Format de snapshot invalide.", file=sys.stderr)
        sys.exit(1)

    only = {s.strip() for s in args.only.split(",")} if args.only else None

    for article in articles:
        if only is not None and article["slug"] not in only:
            continue
        import_article(args.base_url, token, article)


if __name__ == "__main__":
    main()
