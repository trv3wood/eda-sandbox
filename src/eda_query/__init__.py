"""Offline, read-only queries over prebuilt EDA JSON artifacts."""

from .core import catalog_bundle, query_bundle, raw_query, validate_result

__all__ = ["catalog_bundle", "query_bundle", "raw_query", "validate_result"]
