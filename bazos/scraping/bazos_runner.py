from datetime import datetime, timedelta, timezone
from random import uniform
from time import sleep

from bazos.models import Query, QueryRun
from bazos.scraping.bazos_query_runner import BazosQueryRunner
from bazos.scraping.interval_multiplier import NightMultiplier
from django.conf import settings

from ip_changer.tor import TorIPChanger
from senders.models import Discord
from senders.services.discord_sender import DiscordSender


class BazosRunner:
    interval_multiplier_class = NightMultiplier
    ip_changer_class = TorIPChanger

    def __init__(self):
        loggers = Discord.objects.filter(for_logging=True)
        self.interval_multiplier = self.interval_multiplier_class()
        # loggers = session.query(Discord) \
        #     .filter(DiscordSenderDB.for_logging == True) \
        #     .all()  # TODO move elsewhere, controller?
        self.loggers = [DiscordSender.from_model(s) for s in loggers]
        self.ip_changer = self.ip_changer_class(skip_1st_renew=False)

    def run(self):

        while True:
            self.log(f"Waking up at {datetime.utcnow()} UTC")
            # disable old random queries
            Query.objects.filter(randomly_generated=True).update(enabled=False)
            queries = Query.objects.filter(enabled=True).order_by('?')
            # rnd_queries = Query.generate_random_queries(2)
            # self.change_ip()

            # # TODO change so that on 1st run, it will force change_ip
            # # change IP if blacklisted
            # if self.ip_changer.check_bazos_blacklisted():
            #     self.log("IP got BLACKLISTED, attempting to change")
            #     self.change_ip()
            #
            # if self.ip_changer.check_ip_local():
            #     self.log("WARNING: IP IS LOCAL")
            #     continue

            start = datetime.now(timezone.utc)
            for query in queries:
                self.log(f"running query {query}")

                # change IP if blacklisted
                if self.ip_changer.check_bazos_blacklisted(query.url):
                    self.log("IP got BLACKLISTED, attempting to change")
                    self.change_ip(query.url)

                if self.ip_changer.check_ip_local():
                    self.log("WARNING: IP IS LOCAL")
                    continue

                # timediff = max(timedelta(0), second_query.next_runtime - current_datetime)
                query_run = QueryRun(
                    query=query,
                    run_start=datetime.now(timezone.utc),
                    # run_end=end,
                    # new_ads_count=new_products_count,
                )
                query_runner = BazosQueryRunner(query, self.ip_changer.session)
                new_products_count = query_runner.run()
                query.save()
                query_run.run_end = datetime.now(timezone.utc)
                query_run.new_ads_count = new_products_count
                query_run.save()
                print(f"Found {new_products_count} new products for query {query}")
                # for product in query_runner.run():
                #     # if exists
                #     pass
            # else:
            #     self.log(f"waiting for query {first_query}")
            #     timediff = first_query.next_runtime - current_datetime

            # session.commit()
            end = datetime.now(timezone.utc)

            self.log(f"Finished running {len(queries)} queries in {end - start}. End time: {end}")
            sleep_interval = self.get_next_interval()
            self.log(f"sleeping for {sleep_interval}")
            # sleep(timedelta.total_seconds(timediff))
            sleep(sleep_interval)

    def get_next_interval(self):
        multiplier = self.interval_multiplier.get_current_multiplier()
        return multiplier * uniform(settings.INTERVAL_LOWER, settings.INTERVAL_UPPER)

    def log(self, message: str):
        # print message without special characters
        print(message.encode('ascii', 'ignore').decode('ascii'))

        for logger in self.loggers:
            logger.send_plain(message)

    def change_ip(self, url):
        self.log(f"Changing IP, current={self.ip_changer.get_current_ip()}")
        new_ip = self.ip_changer.renew_ip_bazos_ok(url)
        self.log(f"NEW IP={new_ip}")
