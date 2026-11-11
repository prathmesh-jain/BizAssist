import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


class _SuccessfulHealthCheckFilter(logging.Filter):
    """Drop uvicorn access-log lines for successful GET /health calls.

    Docker's healthcheck (docker-compose.yml) hits /health every 15 seconds for as long as the
    container runs, which otherwise buries real requests. Failed checks are still logged.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn.access records carry (client_addr, method, path, http_version, status_code).
        args = record.args
        if isinstance(args, tuple) and len(args) >= 5:
            path, status = str(args[2]).split("?", 1)[0], args[4]
            if path == "/health" and status == 200:
                return False
        return True


def setup_logging():
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    # File (daily rotation): logs/app.log, logs/app.log.YYYY-MM-DD
    fh = TimedRotatingFileHandler(
        filename=str(logs_dir / "app.log"),
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
        utc=False,
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Ensure our modules log at INFO by default
    logging.getLogger("app").setLevel(logging.INFO)

    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    # Hide the every-15-seconds Docker healthcheck from the access log (failures still show).
    logging.getLogger("uvicorn.access").addFilter(_SuccessfulHealthCheckFilter())
