
# def get_sleep_length(next_query):
#     pass
# from src.db import db
from datetime import datetime, timedelta
from ipaddress import ip_network, ip_address
from time import sleep

# from src.db.db import engine
from settings import SETTINGS
from src.models import QueryDB, session, DiscordSenderDB
from src.notifiers.bazos_query_runner import BazosQueryRunner
from src.senders.discord_sender import DiscordSender
from src.tor import IPChanger


class BazosRunner:
    def __init__(self):
        logger_entries = session.query(DiscordSenderDB) \
            .filter(DiscordSenderDB.for_logging == True) \
            .all()  # TODO move elsewhere, controller?
        self.loggers = [DiscordSender.from_db(s) for s in logger_entries]
        self.ip_changer = IPChanger(skip_1st_renew=False)

    def run(self):
        self.change_ip()

        while True:
            self.log(f"Waking up at {datetime.utcnow()} UTC")
            queries = session.query(QueryDB) \
                .order_by(QueryDB.next_runtime) \
                .filter(QueryDB.enabled == True) \
                .limit(2)
            first_query = queries[0]
            second_query = queries[1]
            # first_query, second_query = queries
            current_datetime = datetime.utcnow()
            timediff = timedelta(0)
            if first_query.next_runtime < current_datetime:
                self.log(f"running query {first_query}")

                # change IP if blacklisted
                if self.ip_changer.check_bazos_blacklisted():
                    self.log("IP got BLACKLISTED, attempting to change")
                    self.change_ip()

                if self.check_ip_local():
                    self.log("WARNING: IP IS LOCAL")
                    continue

                timediff = max(timedelta(0), second_query.next_runtime - current_datetime)
                query_runner = BazosQueryRunner(first_query)
                query_runner.run()
                # for product in query_runner.run():
                #     # if exists
                #     pass
            else:
                self.log(f"waiting for query {first_query}")
                timediff = first_query.next_runtime - current_datetime

            session.commit()

            self.log(f"sleeping for {timediff}")
            sleep(timedelta.total_seconds(timediff))

    def log(self, message: str):
        print(f"BazosRunner: {message}")
        for logger in self.loggers:
            logger.send_plain(message)

    def change_ip(self):
        self.log(f"Changing IP, current={self.ip_changer.get_current_ip()}")
        new_ip = self.ip_changer.renew_ip_bazos_ok()
        self.log(f"NEW IP={new_ip}")

    def check_ip_local(self) -> bool:
        return ip_address(self.ip_changer.get_current_ip()) in ip_network(SETTINGS.LOCAL_IP_SUBNET)
