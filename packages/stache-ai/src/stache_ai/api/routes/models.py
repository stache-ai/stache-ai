"""Model selection endpoints - Dynamic model listing based on LLM provider"""

import logging

from fastapi import APIRouter

from stache_ai.rag.pipeline import get_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/models")
async def list_models() -> dict:
    """
    List available LLM models for query synthesis.

    Returns models from the configured LLM provider.
    Models are grouped by capability tier (fast, balanced, premium).
    """
    pipeline = get_pipeline()
    llm_provider = pipeline.llm_provider

    models = llm_provider.get_available_models()
    default_model = llm_provider.get_default_model()

    # Group models by tier for frontend display
    grouped = {
        "fast": [],
        "balanced": [],
        "premium": []
    }

    for model in models:
        model_dict = model.to_dict()
        tier = model_dict.get("tier", "balanced")
        if tier in grouped:
            grouped[tier].append(model_dict)

    return {
        "models": [m.to_dict() for m in models],
        "grouped": grouped,
        "default": default_model,
        "provider": llm_provider.get_name()
    }
