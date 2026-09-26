"""Build the daily digest, and either print it or post it.

`--dry-run` is the point of having a command at all: the job itself is reachable from the
admin's Run-a-job page, but that posts. This renders the exact payload against real data so
the QuickChart URLs can be opened and the embed budget checked before Discord sees any of it.
"""
import json

from django.core.management.base import BaseCommand

from bazos.digest.collect import collect
from bazos.digest.render import render
from senders.models import Discord
from senders.services.discord_webhook import check_payload, embed_chars, post_embeds


class Command(BaseCommand):
    help = "Render the daily Discord digest; post it unless --dry-run."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Print the payload instead of posting it.")
        parser.add_argument("--no-charts", action="store_true",
                            help="Omit the chart images, leaving the text readable in a terminal.")

    def handle(self, *args, **options):
        embeds = render(collect(), charts=not options["no_charts"])
        check_payload(embeds)

        if options["dry_run"]:
            self.stdout.write(json.dumps({"embeds": embeds}, indent=2, ensure_ascii=False))
            self.stdout.write(self.style.SUCCESS(
                f"{len(embeds)} embed(s), {embed_chars(embeds)}/6000 chars — not posted"
            ))
            return

        channels = list(Discord.objects.filter(for_daily_digest=True))
        if not channels:
            self.stdout.write(self.style.WARNING("no Discord row has for_daily_digest set"))
            return
        for channel in channels:
            post_embeds(channel.url, embeds)
            self.stdout.write(self.style.SUCCESS(f"posted to {channel.channel_name}"))
