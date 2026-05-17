"""Copilot model listing with tolerant billing parsing.

The Copilot API occasionally omits the ``multiplier`` field from billing
objects in model list responses.  The SDK's ``ModelBilling.from_dict`` treats
it as required and raises ``ValueError``, which crashes ``list_models()`` and
leaves the model cache empty.

``fetch_copilot_models_raw`` fetches the raw JSON-RPC response directly,
applies ``.setdefault("multiplier", 1.0)`` before parsing, and skips
individual malformed models rather than aborting the whole list.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


async def fetch_copilot_models_raw() -> list[dict]:
    """Start a CopilotClient, fetch raw model dicts, and stop it.

    Tolerates missing ``billing.multiplier`` by defaulting it to ``1.0``
    before handing each dict to the SDK's ``ModelInfo.from_dict``.  Models
    that still fail to parse are skipped individually rather than aborting the
    whole list.

    Returns a list of dicts suitable for storing in ``CachedModelsBySdk``.
    """
    from copilot import CopilotClient
    from copilot.client import ModelInfo

    client = CopilotClient()
    await client.start()
    try:
        # pylint: disable=protected-access  # JsonRpcClient not exposed publicly
        if not client._client:  # noqa: SLF001
            raise RuntimeError("CopilotClient started but internal RPC client is not set")
        response = await client._client.request("models.list", {})  # noqa: SLF001
        models: list[dict] = []
        for raw in response.get("models", []):
            if isinstance(raw.get("billing"), dict):
                raw["billing"].setdefault("multiplier", 1.0)
            try:
                models.append(ModelInfo.from_dict(raw).to_dict())
            except (ValueError, KeyError, TypeError) as exc:
                log.debug("copilot_model_parse_skipped", model_id=raw.get("id"), error=str(exc))
        return models
    finally:
        await client.stop()
