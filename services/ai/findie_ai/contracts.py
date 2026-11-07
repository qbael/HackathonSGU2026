"""Validate public data at the broker boundary before using models or storage."""

from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


from .images import ReviewedRegion
from .ranking import MAX_SEARCH_CANDIDATES


Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Version = Annotated[int, Field(gt=0, strict=True)]
SchemaVersion = Annotated[int, Field(ge=1, le=1, strict=True)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Metadata(Contract):
    schemaVersion: SchemaVersion
    modelId: str
    modelRevision: str
    deadlineAt: AwareDatetime
    cacheScope: UUID | None = Field(default=None, exclude=True)

    def remaining(self):
        if self.deadlineAt.tzinfo is None:
            raise ValueError("deadline_timezone_required")
        remaining = (self.deadlineAt - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            raise TimeoutError("deadline_expired")
        image_operation = isinstance(self, (RedactMetadata, ImageEmbeddingMetadata)) or isinstance(self, SearchMetadata) and self.mode == "image"
        maximum = (960 if isinstance(self, BatchSearchMetadata) else
                   320 if isinstance(self, SearchMetadata) and self.mode == "image" else
                   50 if isinstance(self, SearchMetadata) else 305 if image_operation else 35)
        if remaining > maximum:
            raise ValueError("deadline_too_long")
        return remaining


class IndexMetadata(Metadata):
    jobId: UUID
    leaseToken: UUID
    itemId: UUID
    documentVersion: Version
    snapshotSha256: Digest
    dimensions: Annotated[int, Field(gt=0, le=16000, strict=True)]


class IndexImageMetadata(IndexMetadata):
    sourceId: UUID
    sourceVersion: Version
    sourceSha256: Digest
    processingProfile: Literal["image-v1"]


class IndexVectorMetadata(IndexImageMetadata):
    payloadSha256: Digest


class ImageEmbeddingMetadata(Metadata):
    imageId: UUID
    itemId: UUID
    sourceVersion: Version
    sourceSha256: Digest
    dimensions: Annotated[int, Field(gt=0, le=16000, strict=True)]
    processingProfile: Literal["image-v1"]
    omitOcr: bool = Field(default=False, strict=True)
    coarsePreview: bool = Field(default=False, strict=True)


class OcrMetadata(Contract):
    text: str = Field(max_length=3000, strict=True)
    hasUnclearText: bool = Field(strict=True)
    modelId: str = Field(min_length=1, max_length=200)
    modelRevision: str = Field(min_length=1, max_length=200)
    processingProfile: Literal["ocr-v1"]


class OriginalEmbedding(Contract):
    modelId: str
    modelRevision: str
    dimensions: Annotated[int, Field(gt=0, le=16000, strict=True)]
    sourceSha256: Digest
    vector: list[Annotated[float, Field(strict=True, allow_inf_nan=False)]] = Field(min_length=1, max_length=16000)
    ocr: OcrMetadata | None = None

    @model_validator(mode="after")
    def valid(self):
        if len(self.vector) != self.dimensions or not any(self.vector):
            raise ValueError("invalid_original_embedding")
        return self


class SavedSearchMetadata(Metadata):
    dimensions: Annotated[int, Field(gt=0, le=16000, strict=True)]


class SavedSearchQuery(Contract):
    text: str | None = Field(default=None, max_length=2000, strict=True)
    images: list[OriginalEmbedding] = Field(default_factory=list, max_length=3)
    from_: date | None = Field(default=None, alias="from")
    until: date | None = None
    afterItemId: UUID | None = None

    @model_validator(mode="after")
    def valid(self):
        self.text = self.text.strip() or None if self.text is not None else None
        if not self.text and not self.images:
            raise ValueError("empty_saved_search")
        if any(image.ocr is not None for image in self.images):
            raise ValueError("saved_search_ocr_forbidden")
        if self.from_ == date.min or self.until == date.max or self.from_ and self.until and self.from_ > self.until:
            raise ValueError("invalid_date_range")
        return self


class RedactMetadata(Metadata):
    imageId: UUID
    itemId: UUID
    sourceVersion: Version
    sourceSha256: Digest
    processingProfile: Literal["redact-v4"]
    coarsePreview: bool = Field(default=False, strict=True)
    reviewedRegions: list[ReviewedRegion] | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def valid_masks(self):
        if self.coarsePreview and self.reviewedRegions is not None:
            raise ValueError("conflicting_redaction_modes")
        return self


class SearchMetadata(Metadata):
    processingProfile: Literal["text-v1", "image-v1"]
    searchProfileId: str
    searchProfileVersion: SchemaVersion
    mode: Literal["text", "image"]
    area: str | None = Field(default=None, max_length=200)
    from_: date | None = Field(default=None, alias="from")
    until: date | None = None
    limit: Annotated[int, Field(ge=1, le=10, strict=True)]
    candidateLimit: Annotated[int, Field(ge=1, le=MAX_SEARCH_CANDIDATES, strict=True)]


    @model_validator(mode="after")
    def valid(self):
        if self.processingProfile != ("text-v1" if self.mode == "text" else "image-v1"):
            raise ValueError("search_modality_mismatch")
        if self.from_ == date.min or self.until == date.max or self.from_ and self.until and self.from_ > self.until:
            raise ValueError("invalid_date_range")
        return self


class SearchImage(Contract):
    contentType: Literal["image/jpeg", "image/png", "image/webp"]
    length: Annotated[int, Field(ge=1, le=10 * 1024 * 1024, strict=True)]


class BatchSearchMetadata(Metadata):
    processingProfile: Literal["multimodal-v1"]
    searchProfileId: Literal["image-fusion-v1", "multimodal-fusion-v1"]
    searchProfileVersion: SchemaVersion
    mode: Literal["image", "combined"]
    area: str | None = Field(default=None, max_length=200)
    from_: date | None = Field(default=None, alias="from")
    until: date | None = None
    limit: Annotated[int, Field(ge=1, le=10, strict=True)]
    candidateLimit: Annotated[int, Field(ge=1, le=MAX_SEARCH_CANDIDATES, strict=True)]
    text: str | None = Field(default=None, max_length=2000, strict=True, exclude=True)
    images: list[SearchImage] = Field(min_length=1, max_length=3, exclude=True)

    @model_validator(mode="after")
    def valid(self):
        self.text = self.text.strip() or None if self.text is not None else None
        if (self.mode, self.searchProfileId) != (("combined", "multimodal-fusion-v1") if self.text else ("image", "image-fusion-v1")):
            raise ValueError("search_modality_mismatch")
        if self.from_ == date.min or self.until == date.max or self.from_ and self.until and self.from_ > self.until:
            raise ValueError("invalid_date_range")
        return self


class Query(Contract):
    text: str = Field(min_length=1, max_length=2000)
    area: str | None = Field(default=None, max_length=200)
    from_: date | None = Field(default=None, alias="from")
    until: date | None = None

    @model_validator(mode="after")
    def valid(self):
        self.text = self.text.strip()
        if not self.text or self.from_ == date.min or self.until == date.max:
            raise ValueError("invalid_query")
        if self.from_ and self.until and self.from_ > self.until:
            raise ValueError("invalid_date_range")
        return self


class Custody(Contract):
    kind: Literal["person", "point", "external"]
    displayName: str | None = None
    pointId: UUID | None = None
    name: str | None = None
    publicAddress: str | None = None
    instructions: str | None = None


class PublicDocument(Contract):
    title: str = Field(min_length=1, max_length=200)
    publicDescription: str = Field(min_length=1, max_length=5000)
    foundArea: str = Field(min_length=1, max_length=200)
    foundTimePrecision: Literal["unknown", "date", "range", "exact"]
    foundOn: date | None
    foundFrom: AwareDatetime | None
    foundUntil: AwareDatetime | None
    foundTimezone: str
    custody: Custody


class TextSource(Contract):
    kind: Literal["text"]
    id: UUID
    version: Version
    sha256: Digest
    processingProfile: Literal["text-v1"]


class ImageSource(Contract):
    kind: Literal["image"]
    id: UUID
    version: Version
    sha256: Digest
    processingProfile: Literal["image-v1"]


class Snapshot(Contract):
    schemaVersion: SchemaVersion
    itemId: UUID
    documentVersion: Version
    kind: Literal["snapshot", "tombstone"]
    document: PublicDocument | None
    sources: list[TextSource | ImageSource] = Field(max_length=6)

    @model_validator(mode="after")
    def valid(self):
        if self.kind == "tombstone":
            if self.document is not None or self.sources:
                raise ValueError("invalid_tombstone")
        elif self.document is None or sum(source.kind == "text" for source in self.sources) != 1:
            raise ValueError("text_source_required")
        else:
            if len({source.id for source in self.sources}) != len(self.sources):
                raise ValueError("duplicate_source")
            source = next(source for source in self.sources if source.kind == "text")
            text = self.document.title + "\n" + self.document.publicDescription
            if source.id != self.itemId or source.sha256 != sha256(text.encode()).hexdigest():
                raise ValueError("text_source_mismatch")
        return self

    def embedding_text(self):
        doc = self.document
        return f"{doc.title}\n{doc.publicDescription}\nKhu vực nhặt được: {doc.foundArea}"
