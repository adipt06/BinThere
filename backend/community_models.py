"""Strict contracts for image classification and anonymous community reports."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

FacilityType = Literal['Trash Bin', 'Restroom', 'Recycling Location']

class FacilityRecognition(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    facility_type: Literal['Trash Bin', 'Restroom', 'Recycling Location', 'unknown']
    confidence: float = Field(ge=0, le=1)
    description: str = Field(min_length=1, max_length=600)
    suggested_name: str = Field(min_length=1, max_length=120)

class FacilitySubmission(BaseModel):
    model_config = ConfigDict(extra='forbid')
    recognition_token: str = Field(min_length=20, max_length=200)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=120)
    location_source: Literal['gps', 'address']
    address_token: str | None = Field(default=None, max_length=200)
    public_access_confirmed: Literal[True]

class FacilityReport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: Literal['not_here', 'fraudulent', 'not_public']
