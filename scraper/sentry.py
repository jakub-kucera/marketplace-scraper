"""What gets reported to Sentry, and how it groups. Kept out of settings.py so it can be tested."""
import re

from sentry_sdk.types import Event, Hint

#: Interactive sessions. A typo at the prompt is not a production error, but inside a Pi
#: container it carries the production environment and release like any daemon does.
INTERACTIVE_COMMANDS = frozenset({"shell", "dbshell"})

#: django-q formats a random human-readable name into each message - a cluster name, a task
#: name, a worker process id - so every occurrence of one failure opened its own issue:
#: 12 for one failed cluster start, 5 for one weekly job timing out.
_DJANGO_Q_NAMES = (
    (re.compile(r"\b[a-z]+(?:-[a-z]+){3}\b"), "<name>"),
    (re.compile(r"Process-[0-9a-f]{32}"), "Process-<id>"),
    (re.compile(r" : Traceback.*", re.DOTALL), ""),
)


def should_report(dsn: str, argv: list[str], running_tests: bool) -> bool:
    if not dsn or running_tests:
        return False
    return not (len(argv) > 1 and argv[1] in INTERACTIVE_COMMANDS)


def before_send(event: Event, hint: Hint) -> Event:
    if event.get("logger") == "django-q":
        message = str((event.get("logentry") or {}).get("message") or "")
        for pattern, replacement in _DJANGO_Q_NAMES:
            message = pattern.sub(replacement, message)
        event["fingerprint"] = ["django-q", message]
    return event
