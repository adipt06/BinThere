"""Strict waste-assistant response contract; model output never becomes a map location."""
import re
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Category = Literal['recycling', 'compost', 'landfill', 'hazardous', 'ewaste', 'donate', 'dropoff', 'unknown']
ShortText = Annotated[str, Field(min_length=1, max_length=600)]

class WasteItem(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: Annotated[str, Field(min_length=1, max_length=120)]
    material: Annotated[str, Field(min_length=1, max_length=160)]
    bin: Category
    steps: Annotated[list[ShortText], Field(min_length=1, max_length=5)]
    tip: ShortText | None

    @model_validator(mode='after')
    def reject_unsafe_ordinary_disposal(self):
        if self.bin in ('landfill', 'recycling', 'compost') and re.search(
                r'batter(?:y|ies)|lithium|chemical|paint|bulb|electronic|phone|computer|medical|needle',
                self.name + ' ' + self.material, re.IGNORECASE):
            raise ValueError('Special waste cannot be recommended for ordinary bins.')
        return self

class WasteAnalysis(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    answer: Annotated[str, Field(min_length=1, max_length=2400)] | None
    summary: ShortText
    items: Annotated[list[WasteItem], Field(max_length=8)]
    unsure: Annotated[str, Field(min_length=1, max_length=1200)] | None
