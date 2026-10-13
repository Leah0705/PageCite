"""
Fake unstructured element factories used in ingest tests.

Keeping element construction here isolates tests from unstructured's internal
class hierarchy. Only the attributes ingest.py actually reads are required.
"""
from __future__ import annotations

from types import SimpleNamespace


def _meta(page: int = 1, **kwargs) -> SimpleNamespace:
    return SimpleNamespace(page_number=page, **kwargs)


def make_narrative(text: str, page: int = 1):
    from unstructured.documents.elements import NarrativeText
    el = NarrativeText(text=text)
    el.metadata = _meta(page=page)
    return el


def make_title(text: str, page: int = 1):
    from unstructured.documents.elements import Title
    el = Title(text=text)
    el.metadata = _meta(page=page)
    return el


def make_table(text: str, html: str, page: int = 1):
    from unstructured.documents.elements import Table
    el = Table(text=text)
    el.metadata = _meta(page=page, text_as_html=html)
    return el


def make_image(image_path: str, page: int = 1):
    from unstructured.documents.elements import Image as UnstructuredImage
    el = UnstructuredImage(text="")
    el.metadata = _meta(page=page, image_path=image_path)
    return el


SAMPLE_HTML_TABLE = (
    "<table>"
    "<tr><th>Model</th><th>BLEU</th></tr>"
    "<tr><td>Transformer (base)</td><td>27.3</td></tr>"
    "<tr><td>Transformer (big)</td><td>28.4</td></tr>"
    "</table>"
)

SAMPLE_NARRATIVE = (
    "The dominant sequence transduction models are based on complex recurrent or "
    "convolutional neural networks. We propose a new simple network architecture, "
    "the Transformer, based solely on attention mechanisms."
)
