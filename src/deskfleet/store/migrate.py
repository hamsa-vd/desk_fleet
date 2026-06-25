"""Apply schema.sql on startup. CREATE ... IF NOT EXISTS only; nothing here ever drops."""

from pathlib import Path

from deskfleet.config import get_logger
from deskfleet.store import repository

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

logger = get_logger(__name__)


def read_schema() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


def migrate() -> None:
    try:
        with repository._connect() as connection, connection.cursor() as cursor:
            cursor.execute(read_schema())
        logger.info("store_migrated")
    except Exception as exc:
        logger.error("store_migration_failed", extra={"cause": str(exc)})
