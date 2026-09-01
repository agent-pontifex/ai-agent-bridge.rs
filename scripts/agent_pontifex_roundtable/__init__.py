"""Public surface for the four-provider Agent Pontifex conformance harness."""

from .common import ConformanceError, HttpJsonError, ProviderResult, load_matrix
from .providers import invoke_provider, provider_request, provider_response_text
from .protocol import assert_substitution_acknowledged, make_publish_body
from .runner import run_roundtable

__all__ = [
    "ConformanceError",
    "HttpJsonError",
    "ProviderResult",
    "assert_substitution_acknowledged",
    "invoke_provider",
    "load_matrix",
    "make_publish_body",
    "provider_request",
    "provider_response_text",
    "run_roundtable",
]
