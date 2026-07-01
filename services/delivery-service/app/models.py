from __future__ import annotations

from pydantic import BaseModel


class AuthRequest(BaseModel):
    init_data: str


class AuthResponse(BaseModel):
    session_token: str
    user_id: str
    role: str


class FeedItem(BaseModel):
    movement_id: str
    name: str
    style_id: str
    price_stars: int
    teaser_url: str | None
    created_at: str | None


class VariantItem(BaseModel):
    variant_id: str
    movement_id: str
    style_id: str
    avatar_id: str
    price_stars: int
    entitled: bool
    # Un-entitled variants have no free preview: only a blurred poster.
    teaser_url: str | None
    locked: bool
    blurred: bool


class ProgressRequest(BaseModel):
    movement_id: str
    variant_id: str | None = None
    seconds: float


class ProgressResponse(BaseModel):
    seconds_watched: float
    locked: bool
    free_preview_seconds: int


class InvoiceRequest(BaseModel):
    # exactly one of movement_id / variant_id / subscription_tier
    movement_id: str | None = None
    variant_id: str | None = None
    subscription_tier: str | None = None


class InvoiceResponse(BaseModel):
    invoice_link: str
