"""The admin's "Run a job" page — pick a job, type an id, it goes on the queue.

The third way to reach a job, alongside the changelist actions (when you are already looking
at the row) and the schedules (when it is periodic). This one is for when all you have is an
id.

**Why not just use django-q2's Schedule admin**, which will already enqueue anything with
`schedule_type=Once`? Because nothing there is checked. The dotted path is typed by hand, so
a typo becomes a `Failure` row in a worker nobody is watching — the exact trap
`bazos/jobs.py` declares its path constants to avoid. The id is not checked either, so a
wrong one fails the same way, ten seconds later and somewhere else. And it leaves a stray
`Schedule` row behind afterwards.

Here the path comes from `JOB_CATALOG` and **the argument is resolved before anything is
queued**, so a mistake is a form error on the page you are looking at.
"""
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django_q.tasks import async_task

from bazos.jobs import AD_PK, JOB_CATALOG, NO_ARG, POSTAL_CODE, PUBLISHER_REF


class RunJobForm(forms.Form):
    """Choose a job and, if it takes one, an argument that must resolve *now*."""

    job = forms.ChoiceField(label="Job")
    argument = forms.CharField(
        label="Argument", required=False,
        help_text="Ad id, postal code, or a seller as email:123 / phone:456. "
                  "Leave blank for a job that takes none.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Built per instance, not at import: another app registers its jobs at
        # `AppConfig.ready()`, which runs after this module is imported.
        job_field = self.fields["job"]
        assert isinstance(job_field, forms.ChoiceField)  # for mypy; declared as one above
        job_field.choices = [
            (func, spec.label) for func, spec in sorted(
                JOB_CATALOG.items(), key=lambda item: item[1].label
            )
        ]

    def clean(self) -> dict:
        cleaned: dict = super().clean() or {}
        func = cleaned.get("job")
        if not func:
            return cleaned

        spec = JOB_CATALOG[func]
        raw = (cleaned.get("argument") or "").strip()

        if spec.arg == NO_ARG:
            if raw:
                # Not ignored silently: someone who typed an id meant it to be used, and a
                # job that quietly discards it would look like it ran on the wrong thing.
                raise forms.ValidationError(f"{spec.label} takes no argument.")
            cleaned["task_args"] = ()
            return cleaned

        if not raw:
            raise forms.ValidationError(f"{spec.label} needs an argument.")
        cleaned["task_args"] = self._resolve(spec, raw)
        return cleaned

    def _resolve(self, spec, raw: str) -> tuple:
        """Turn the typed argument into task args, or raise a form error.

        Resolving here rather than in the task is the whole point of this page: a bad id
        should fail in front of you, not as a `Failure` row a worker writes later.
        """
        from bazos.geo import normalize_postal_code
        from bazos.models import Ad, EmailPublisher, PhonePublisher

        if spec.arg == AD_PK:
            if not raw.isdigit() or not Ad.objects.filter(pk=int(raw)).exists():
                raise forms.ValidationError(f"No Ad with id {raw!r}.")
            return (int(raw),)

        if spec.arg == POSTAL_CODE:
            code = normalize_postal_code(raw)
            if not code:
                raise forms.ValidationError(f"{raw!r} is not a usable postal code.")
            return (code,)

        if spec.arg == PUBLISHER_REF:
            kind, _, pk = raw.partition(":")
            kind = kind.strip().lower()
            # Branched below rather than looked up in a dict for the reason `_publisher` in
            # `bazos/jobs.py` gives: a dict of these two model classes erases both to their
            # shared abstract base, which has no manager.
            if kind not in ("email", "phone") or not pk.strip().isdigit():
                # A seller is a *pair* of ids in two tables, so the number alone is
                # ambiguous — which is why the kind is part of what you type.
                raise forms.ValidationError(
                    "Give a seller as email:123 or phone:456 — the number alone does not "
                    "say which of the two publisher tables it is in."
                )
            model = EmailPublisher if kind == "email" else PhonePublisher
            if not model.objects.filter(pk=int(pk)).exists():
                raise forms.ValidationError(f"No {kind} publisher with id {pk}.")
            return (kind, int(pk))

        raise forms.ValidationError(f"Don't know how to read an argument for {spec.arg!r}.")


def run_job_view(request):
    """GET renders the form; POST validates, enqueues, and comes back with a message."""
    # Unfold's action decorator already wraps this in `admin_view`, so an anonymous or
    # non-staff visitor is redirected to the login page and never arrives. Kept as defence
    # for a direct call — and `PermissionDenied` rather than `PermissionError`, because only
    # the former is a 403 rather than a 500.
    if not request.user.is_staff:
        raise PermissionDenied

    form = RunJobForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        func = form.cleaned_data["job"]
        args = form.cleaned_data["task_args"]
        task_id = async_task(func, *args)
        messages.info(
            request,
            f"Queued {JOB_CATALOG[func].label}"
            + (f" ({', '.join(str(a) for a in args)})" if args else "")
            + f" — task {task_id}. The result appears in Successful/Failed tasks.",
        )
        return HttpResponseRedirect(request.path)

    return render(request, "admin/run_job.html", {
        **admin.site.each_context(request),
        "title": "Run a job",
        "form": form,
        "catalog": sorted(JOB_CATALOG.values(), key=lambda s: s.label),
        "schedules_url": reverse("admin:django_q_schedule_changelist"),
    })
