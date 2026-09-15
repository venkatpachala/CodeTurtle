import logging
import os
from dotenv import load_dotenv

load_dotenv()

class _KwargsLogger:
    """stdlib logger that accepts structlog-style keyword fields."""

    def __init__(self, inner: logging.Logger):
        self._inner = inner

    def _emit(self, level: str, msg: str, *args, **kwargs):
        kwargs.pop("exc_info", None)
        kwargs.pop("stack_info", None)
        kwargs.pop("stacklevel", None)
        extra = kwargs.pop("extra", None) or {}
        fields = {k: v for k, v in kwargs.items()}
        if fields:
            msg = f"{msg} | {fields}"
        log = getattr(self._inner, level)
        if extra:
            log(msg, *args, extra=extra)
        else:
            log(msg, *args)

    def debug(self, msg, *args, **kwargs):
        self._emit("debug", msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._emit("info", msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._emit("warning", msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._emit("error", msg, *args, **kwargs)


try:
    import structlog

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
    )
    logger = structlog.get_logger()
except ImportError:
    logging.basicConfig(level=logging.INFO)
    logger = _KwargsLogger(logging.getLogger("codeturtle"))


def get_langfuse_handler():
    """Initialize Langfuse when the optional extra and keys are present."""
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")

    if not public_key or not secret_key:
        logger.warning("Langfuse keys not found. Observability disabled.")
        return None

    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        logger.warning("Langfuse extra not installed. Observability disabled.")
        return None

    try:
        handler = CallbackHandler()
        logger.info("Langfuse observability enabled")
        return handler
    except Exception as e:
        logger.error("Failed to initialize Langfuse", extra={"error": str(e)})
        return None


def get_langfuse_client():
    """Return Langfuse client for adding metadata/tags."""
    try:
        from langfuse import Langfuse

        return Langfuse()
    except Exception:
        return None


def get_logger():
    return logger
