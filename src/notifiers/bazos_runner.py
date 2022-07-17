
# def get_sleep_length(next_query):
#     pass
# from src.db import db
from datetime import datetime, timedelta
from time import sleep

# from src.db.db import engine
from src.models import QueryDB, session, DiscordSenderDB
from src.notifiers.bazos_query_runner import BazosQueryRunner
from src.senders.discord_sender import DiscordSender


class BazosRunner:
    def __init__(self):
        logger_entries = session.query(DiscordSenderDB) \
            .filter(DiscordSenderDB.for_logging == True) \
            .all()  # TODO move elsewhere, controller?
        self.loggers = [DiscordSender(s.url, s.notify) for s in logger_entries]

    def log(self, message: str):
        print(f"BazosRunner: {message}")
        for logger in self.loggers:
            logger.send_plain(message)

    def run(self):
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

        #
        # match len(queries):
        #     case 0:
        #         # sleep(1)
        #         continue
        #     case 1:
        #         query = queries[0]
        #         for product in run(query):
        #             db.session.add(product)
        #         continue
        #         # run, but sleep, based on next query next_runtime , could make more abstract
        #     # default:
        #         #also run, but dont sleep
        #         # LOG multiple queries need to be run
        # db.session.commit()

        # db.commit()
