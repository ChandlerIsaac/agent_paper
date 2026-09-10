"""Application-specific exception hierarchy."""


class ResearchMateError(Exception):
    """Base exception for expected application failures."""


class DocumentLoadError(ResearchMateError):
    """Raised when a document cannot be parsed."""


class IndexingError(ResearchMateError):
    """Raised when documents cannot be indexed."""


class RetrievalError(ResearchMateError):
    """Raised when evidence retrieval fails."""


class KnowledgeBaseNotFoundError(ResearchMateError):
    """Raised when a requested knowledge base does not exist."""
