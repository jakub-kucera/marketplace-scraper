from datetime import datetime, timezone
from random import uniform
from time import sleep

from bazos.models import Query, QueryRun
from bazos.scraping.bazos_query_runner import BazosQueryRunner
from bazos.scraping.interval_multiplier import NightMultiplier
from bazos.utils import ascii_safe
from django.conf import settings

from ip_changer.dummy import DummyIPChanger
from ip_changer.tor import TorIPChanger
from senders.models import Discord
from senders.services.discord_sender import DiscordSender


class BazosRunner:

    def __init__(self):
        loggers = Discord.objects.filter(for_logging=True)
        self.interval_multiplier = NightMultiplier()
        self.loggers = [DiscordSender.from_model(s) for s in loggers]
        ip_changer_class = DummyIPChanger if settings.IP_CHANGER_TYPE == "DUMMY" else TorIPChanger
        self.ip_changer = ip_changer_class(skip_1st_renew=False)

    def run(self):
        while True:
            self.log(f"Waking up at {datetime.utcnow()} UTC")
            Query.objects.filter(randomly_generated=True).update(enabled=False)
            queries = Query.objects.filter(enabled=True).order_by('?')

            start = datetime.now(timezone.utc)
            for query in queries:
                self.log(ascii_safe(f"running query {query}"))

                if self.ip_changer.check_bazos_blacklisted(query.url):
                    self.log("IP got BLACKLISTED, attempting to change")
                    self.change_ip(query.url)

                if self.ip_changer.check_ip_local():
                    self.log("WARNING: IP IS LOCAL")
                    continue

                query_run = QueryRun(
                    query=query,
                    run_start=datetime.now(timezone.utc),
                )
                query_runner = BazosQueryRunner(query, self.ip_changer.session)
                new_products_count = query_runner.run()
                query.save()
                query_run.run_end = datetime.now(timezone.utc)
                query_run.new_ads_count = new_products_count
                query_run.save()
                print(ascii_safe(f"Found {new_products_count} new products for query {query}"))

            end = datetime.now(timezone.utc)
            self.log(f"Finished running {len(queries)} queries in {end - start}. End time: {end}")
            sleep_interval = self.get_next_interval()
            self.log(f"sleeping for {sleep_interval}")
            sleep(sleep_interval)

    def get_next_interval(self):
        multiplier = self.interval_multiplier.get_current_multiplier()
        return multiplier * uniform(settings.INTERVAL_LOWER, settings.INTERVAL_UPPER)

    def log(self, message: str):
        print(ascii_safe(message))
        for logger in self.loggers:
            logger.send_plain(message)

    def change_ip(self, url):
        self.log(f"Changing IP, current={self.ip_changer.get_current_ip()}")
        new_ip = self.ip_changer.renew_ip_bazos_ok(url)
        self.log(f"NEW IP={new_ip}")
