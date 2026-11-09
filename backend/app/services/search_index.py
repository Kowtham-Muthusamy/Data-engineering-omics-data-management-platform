"""OpenSearch simulator: a denormalised, rebuildable metadata index in SQLite.

This module is deliberately one-way: state changes call ``index_sample`` to refresh the
document; nothing in the state-tracking layer ever *reads* the index to make a decision.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.tables import CatalogueVersion, Sample, SearchIndex
from app.utils.common import utcnow


def index_sample(session: Session, sample: Sample, metadata: Optional[dict[str, Any]] = None) -> None:
    doc = session.get(SearchIndex, sample.sample_id)
    if doc is None:
        doc = SearchIndex(sample_id=sample.sample_id, run_id=sample.run_id, created_at=sample.created_at,
                          catalogue_version=sample.catalogue_version, processing_status=sample.status,
                          quality_status=sample.quality_status, document={}, text="")
        session.add(doc)
    if metadata is None:
        metadata = (doc.document or {}).get("metadata", {})
    cat = (session.query(CatalogueVersion).filter_by(sample_id=sample.sample_id, version=sample.catalogue_version)
           .order_by(CatalogueVersion.id.desc()).first())
    catalogue = cat.content if cat else {}
    doc.run_id = sample.run_id
    doc.catalogue_version = sample.catalogue_version
    doc.processing_status = sample.status
    doc.quality_status = sample.quality_status
    doc.indexed_at = utcnow()
    doc.document = {
        "sample_id": sample.sample_id, "run_id": sample.run_id,
        "catalogue_version": sample.catalogue_version, "processed_version": sample.processed_version,
        "processing_status": sample.status, "quality_status": sample.quality_status,
        "s3_destination": sample.s3_destination, "metadata": metadata, "catalogue": catalogue,
    }
    doc.text = " ".join(str(v) for v in [sample.sample_id, sample.run_id, sample.catalogue_version, sample.status,
                                         sample.quality_status, *metadata.values(), *catalogue.values()]).lower()


def search(session: Session, *, q: Optional[str] = None, sample_id: Optional[str] = None,
           run_id: Optional[str] = None, catalogue_version: Optional[str] = None,
           processing_status: Optional[str] = None, quality_status: Optional[str] = None,
           created_from: Optional[datetime] = None, created_to: Optional[datetime] = None,
           limit: int = 50, offset: int = 0) -> tuple[int, list[SearchIndex]]:
    query = session.query(SearchIndex)
    if sample_id:
        query = query.filter(SearchIndex.sample_id.ilike(f"%{sample_id}%"))
    if run_id:
        query = query.filter(SearchIndex.run_id.ilike(f"%{run_id}%"))
    if catalogue_version:
        query = query.filter(SearchIndex.catalogue_version == catalogue_version)
    if processing_status:
        query = query.filter(SearchIndex.processing_status == processing_status)
    if quality_status:
        query = query.filter(SearchIndex.quality_status == quality_status)
    if created_from:
        query = query.filter(SearchIndex.created_at >= created_from)
    if created_to:
        query = query.filter(SearchIndex.created_at <= created_to)
    if q:
        for term in q.lower().split():
            query = query.filter(or_(SearchIndex.text.contains(term)))
    total = query.count()
    return total, query.order_by(SearchIndex.created_at.desc(), SearchIndex.sample_id).offset(offset).limit(limit).all()
