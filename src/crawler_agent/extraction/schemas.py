from __future__ import annotations

import datetime as dt
from typing import Literal, Protocol

from pydantic import BaseModel, Field

Status = Literal["enacted", "proposed", "upcoming", "amended", "unknown"]


class ExtractedRegulationItem(BaseModel):
    title: str
    url: str
    summary: str = Field(
        default="",
        description=(
            "A concise (1-3 sentence) plain-language description of what this "
            "regulatory change actually covers or requires -- its subject "
            "matter and key provisions -- grounded only in what the source "
            "text states. Not a verbatim copy of the title."
        ),
    )
    document_number: str | None = Field(
        default=None,
        description=(
            "The official document/citation reference, copied verbatim if one "
            "is given (e.g. a Federal Register document number, a Statutory "
            "Instrument year/number, a CELEX or OJ reference). Null if none is "
            "stated."
        ),
    )
    publication_date: dt.date | None = None
    effective_date: dt.date | None = None
    status: Status = "unknown"
    document_type: str | None = None


class ExtractionResult(BaseModel):
    items: list[ExtractedRegulationItem] = Field(default_factory=list)


class Extractor(Protocol):
    def extract(self, *, page_text: str, page_url: str) -> ExtractionResult: ...
