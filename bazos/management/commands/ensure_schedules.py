"""Create or update the project's recurring schedules. Idempotent; safe on every deploy.

Schedules are `django_q.Schedule` **rows**, not code, which is the point — cadence becomes
editable in the admin without a deploy. But rows in a database nobody declares are rows
nobody can recreate, so `bazos.jobs.SCHEDULES` is the declaration and this command applies
it: it owns `name`, `func` and the default cadence, and leaves everything else alone once a
row exists.

⚠️ It deliberately does **not** overwrite `next_run` or a hand-edited `minutes` on an
existing row. Editing the cadence in the admin is a feature; a deploy silently reverting that
edit would make the admin control a lie.
"""
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule

from bazos.jobs import SCHEDULES


def first_run(spec, now=None):
    """When a *newly created* row should first fire.

    Without `spec.at` this is "now", which for a DAILY row means "24 h after whenever the
    deploy happened" — fine for a prune, useless for something a person reads at a fixed
    time. With it, the next occurrence of that local wall-clock time; django-q2 keeps the
    wall clock across DST from there (see `ScheduleSpec.at`).
    """
    now = now or timezone.now()
    if spec.at is None:
        return now
    local = timezone.localtime(now)
    run = timezone.make_aware(datetime.combine(local.date(), spec.at))
    return run if run > now else run + timedelta(days=1)


class Command(BaseCommand):
    help = "Create the recurring django-q2 schedules if they do not already exist."

    def handle(self, *args, **options):
        # Read at call time, not import time: another app's `AppConfig.ready()` registers
        # into this dict, and `ready()` has already run by the time a command executes.
        for name, spec in SCHEDULES.items():
            schedule, created = Schedule.objects.get_or_create(
                name=name,
                defaults={
                    "func": spec.func,
                    "schedule_type": spec.schedule_type,
                    "minutes": spec.minutes,
                    "repeats": -1,
                    "next_run": first_run(spec),
                    "kwargs": repr(spec.kwargs) if spec.kwargs else "",
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"created schedule {name} -> {spec.func}"))
                continue
            # The dotted path is ours to own — a renamed task must not leave a schedule
            # pointing at an import that no longer resolves, which fails silently at runtime.
            if schedule.func != spec.func:
                schedule.func = spec.func
                schedule.save(update_fields=["func"])
                self.stdout.write(self.style.WARNING(f"repointed {name} -> {spec.func}"))
            else:
                self.stdout.write(f"{name} already scheduled ({schedule.get_schedule_type_display()})")
