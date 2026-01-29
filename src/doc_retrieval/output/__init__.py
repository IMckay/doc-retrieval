"""Output writers for extracted documentation."""

from doc_retrieval.output.multi_file import MultiFileOutput
from doc_retrieval.output.single_file import SingleFileOutput

__all__ = [
    "SingleFileOutput",
    "MultiFileOutput",
]
