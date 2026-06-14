"""Stable public author-handle (slug) generation for users.

The slug powers /author/<slug> URLs and is decoupled from display_name so a
rename never breaks existing links. Generated once, lazily, then fixed.
"""
import re

from app.auth.models import User


def slugify_name(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:110] or "user"


async def ensure_user_slug(user: User) -> str:
    """Return the user's slug, generating a unique one on first need."""
    if user.slug:
        return user.slug
    base = slugify_name(user.display_name or (user.email.split("@")[0] if user.email else ""))
    slug = base
    n = 1
    while await User.filter(slug=slug).exclude(id=user.id).exists():
        n += 1
        slug = f"{base}-{n}"
    user.slug = slug
    await user.save(update_fields=["slug"])
    return slug


async def refresh_author_cache(user: User) -> int:
    """Propagate the user's current name/avatar/slug onto their cached article
    bylines so published bylines never go stale. Returns the row count updated.
    """
    from app.articles.models import Article

    slug = await ensure_user_slug(user)
    return await Article.filter(author_id=user.id).update(
        author=user.display_name or user.email,
        author_avatar=user.avatar_url,
        author_slug=slug,
    )
