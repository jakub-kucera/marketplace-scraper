from datetime import datetime, timedelta, timezone
from random import uniform
from time import sleep

from bazos.models import Query
from bazos.scraping.bazos_query_runner import BazosQueryRunner
from bazos.scraping.interval_multiplier import NightMultiplier
from scraper import settings
from senders.models import Discord
from senders.services.discord_sender import DiscordSender


class BazosRunner:
    interval_multiplier_class = NightMultiplier

    def __init__(self):
        loggers = Discord.objects.filter(for_logging=True)
        self.interval_multiplier = self.interval_multiplier_class()
        # loggers = session.query(Discord) \
        #     .filter(DiscordSenderDB.for_logging == True) \
        #     .all()  # TODO move elsewhere, controller?
        self.loggers = [DiscordSender.from_model(s) for s in loggers]
        # self.ip_changer = TorIPChanger(skip_1st_renew=False)

    def run(self):
        # self.change_ip()

        while True:
            self.log(f"Waking up at {datetime.utcnow()} UTC")
            queries = Query.objects.filter(enabled=True).order_by('?')
            # queries = session.query(QueryDB) \
            #     .order_by(QueryDB.next_runtime) \
            #     .filter(QueryDB.enabled == True) \
            #     .limit(2)
            # first_query = queries[0]
            # second_query = queries[1]
            # # first_query, second_query = queries
            start = datetime.now(timezone.utc)
            # timediff = timedelta(0)
            # if first_query.next_runtime < current_datetime:
            for query in queries:
                self.log(f"running query {query}")

                # change IP if blacklisted
                # if self.ip_changer.check_bazos_blacklisted():
                #     self.log("IP got BLACKLISTED, attempting to change")
                #     self.change_ip()

                # if self.check_ip_local():
                #     self.log("WARNING: IP IS LOCAL")
                #     continue

                # timediff = max(timedelta(0), second_query.next_runtime - current_datetime)
                query_runner = BazosQueryRunner(query)
                query_runner.run()
                query.save()
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
        print(f"BazosRunner: {message}")
        for logger in self.loggers:
            logger.send_plain(message)

    # def change_ip(self):
    #     self.log(f"Changing IP, current={self.ip_changer.get_current_ip()}")
    #     new_ip = self.ip_changer.renew_ip_bazos_ok()
    #     self.log(f"NEW IP={new_ip}")
