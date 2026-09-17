"""Create or update the project's recurring schedules. Idempotent; safe on every deploy.

Schedules are `django_q.Schedule` **rows**, not code, which is the point — cadence becomes
editable in the admin without a deploy. But rows in a database nobody declares are rows
nobody can recreate, so this command is the declaration: it owns `name`, `func` and the
default cadence, and leaves everything else alone once a row exists.

⚠️ It deliberately does **not** overwrite `next_run` or a hand-edited `minutes` on an
existing row. Editing the cadence in the admin is a feature; a deploy silently reverting that
edit would make the admin control a lie.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule

from bazos.jobs import HEARTBEAT, SWEEP_DELISTED

#: name -> (dotted func, schedule_type, minutes, kwargs)
SCHEDULES: dict[str, tuple] = {
    "delisting-sweep": (
        SWEEP_DELISTED,
        Schedule.DAILY,
        None,
        # Daily is the right resolution: `removed_at` is stamped when the sweep notices, so
        # finer cadence buys precision the question ("how many days to disappear") cannot
        # use, at a linear cost in requests.
        {},
    ),
    "cluster-heartbeat": (
        HEARTBEAT,
        Schedule.MINUTES,
        60,
        {},
    ),
}


class Command(BaseCommand):
    help = "Create the recurring django-q2 schedules if they do not already exist."

    def handle(self, *args, **options):
        for name, (func, schedule_type, minutes, kwargs) in SCHEDULES.items():
            schedule, created = Schedule.objects.get_or_create(
                name=name,
                defaults={
                    "func": func,
                    "schedule_type": schedule_type,
                    "minutes": minutes,
                    "repeats": -1,
                    "next_run": timezone.now(),
                    "kwargs": repr(kwargs) if kwargs else "",
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"created schedule {name} -> {func}"))
                continue
            # The dotted path is ours to own — a renamed task must not leave a schedule
            # pointing at an import that no longer resolves, which fails silently at runtime.
            if schedule.func != func:
                schedule.func = func
                schedule.save(update_fields=["func"])
                self.stdout.write(self.style.WARNING(f"repointed {name} -> {func}"))
            else:
                self.stdout.write(f"{name} already scheduled ({schedule.get_schedule_type_display()})")
