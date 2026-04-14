"""Push notification endpoints for Web Push subscription management."""

from __future__ import annotations

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from backend.models.api_schemas import CamelModel
from backend.services.push_service import PushService

router = APIRouter(tags=["notifications"], route_class=DishkaRoute)


class VapidKeyResponse(CamelModel):
    public_key: str


class SubscriptionRequest(CamelModel):
    endpoint: str
    keys: dict[str, str]


class UnsubscribeRequest(CamelModel):
    endpoint: str


@router.get("/notifications/vapid-key", response_model=VapidKeyResponse)
async def get_vapid_key(push_service: FromDishka[PushService]) -> VapidKeyResponse:
    """Return the VAPID public key for Web Push subscription."""
    return VapidKeyResponse(public_key=push_service.public_key)


@router.post("/notifications/subscribe", status_code=204)
async def subscribe(body: SubscriptionRequest, push_service: FromDishka[PushService]) -> None:
    """Register a Web Push subscription."""
    push_service.subscribe({"endpoint": body.endpoint, "keys": body.keys})


@router.post("/notifications/unsubscribe", status_code=204)
async def unsubscribe(body: UnsubscribeRequest, push_service: FromDishka[PushService]) -> None:
    """Remove a Web Push subscription."""
    push_service.unsubscribe(body.endpoint)
