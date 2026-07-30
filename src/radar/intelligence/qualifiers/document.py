"""Vision, OCR, and document-understanding qualification."""

from radar.intelligence.qualifiers.base import PredicateQualifier


class DocumentQualifier(PredicateQualifier):
    required_predicates = ("document_formats",)
    fit_metrics = ("page_limit", "image_resolution")
    risk_checks = ("ocr_languages", "layout_support")
