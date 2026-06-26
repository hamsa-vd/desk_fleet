"""Token accounting.

tiktoken supplies the pre-flight estimate; the provider's reported usage is the source of truth.
"""

import tiktoken

from deskfleet.config import get_logger
from deskfleet.models import get_model_spec
from deskfleet.observability import metrics

logger = get_logger(__name__)

#: Free-text model ids from a custom endpoint would blow up metric cardinality.
UNKNOWN_MODEL_LABEL = "other"

_warned_encodings: set[str] = set()


def model_label(model_id: str) -> str:
    return model_id if get_model_spec(model_id) else UNKNOWN_MODEL_LABEL


def estimate_tokens(text: str, model_id: str) -> int:
    try:
        encoding = tiktoken.encoding_for_model(model_id)
    except Exception:
        if model_id not in _warned_encodings:
            _warned_encodings.add(model_id)
            logger.warning("no_tiktoken_encoding", extra={"model": model_label(model_id)})
        return max(1, len(text) // 4)

    try:
        return len(encoding.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def usd_for(model_id: str, tokens_in: int, tokens_out: int) -> float:
    spec = get_model_spec(model_id)
    if spec is None or spec.price_in_per_m is None or spec.price_out_per_m is None:
        logger.warning("model_not_priced", extra={"model": model_label(model_id)})
        return 0.0
    return (tokens_in * spec.price_in_per_m + tokens_out * spec.price_out_per_m) / 1_000_000


def record_usage(model_id: str, tokens_in: int, tokens_out: int) -> float:
    try:
        label = model_label(model_id)
        usd = usd_for(model_id, tokens_in, tokens_out)
        metrics.observe_tokens(label, tokens_in, tokens_out)
        metrics.observe_cost(label, usd)
        return usd
    except Exception as exc:
        logger.error("usage_recording_failed", extra={"cause": str(exc)})
        return 0.0
