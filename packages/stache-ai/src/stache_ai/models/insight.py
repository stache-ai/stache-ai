"""Data models for insights (user notes with semantic search)"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class InsightCreate(BaseModel):
    """Request model for creating an insight"""
    content: str = Field(..., min_length=1, description="Content of the insight (required)")
    namespace: str = Field(..., description="Namespace for organizing insights")
    tags: Optional[List[str]] = Field(None, description="Optional tags for categorization")


class InsightResponse(BaseModel):
    """Response model for an insight"""
    id: str = Field(..., description="Unique insight ID")
    content: str = Field(..., description="Content of the insight")
    namespace: str = Field(..., description="Namespace the insight belongs to")
    created_at: datetime = Field(..., description="Timestamp when insight was created")
    tags: Optional[List[str]] = Field(None, description="Tags associated with the insight")
