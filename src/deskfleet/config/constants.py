"""Constants shared by more than one module. Business rules belong in policy.md, not here."""

MAX_ITERS = 3
RECURSION_LIMIT = 8
TOKEN_BUDGET_PER_TICKET = 20_000

# M6 S52's retry schedule (30s → 60s, 5 attempts) is sized for a background worker. These calls
# happen inside a synchronous POST /resolve that a user is waiting on, so the pattern is kept and
# the values shrunk: the ceiling below is the worst case a caller can be made to wait on retries.
HTTP_TIMEOUT_S = 10.0
HTTP_MAX_ATTEMPTS = 4
HTTP_BACKOFF_BASE_S = 0.5
HTTP_BACKOFF_FACTOR = 2.0
HTTP_BACKOFF_TOTAL_CEILING_S = 8.0
HTTP_RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

LLM_TIMEOUT_S = 60.0

EMAIL_PLACEHOLDER = "<EMAIL_REDACTED>"
PHONE_PLACEHOLDER = "<PHONE_REDACTED>"
CARD_PLACEHOLDER = "<CARD_REDACTED>"
SSN_PLACEHOLDER = "<SSN_REDACTED>"

KNOWN_LANGCHAIN_ENDPOINTS = (
    "https://api.smith.langchain.com",
    "https://eu.api.smith.langchain.com",
)
