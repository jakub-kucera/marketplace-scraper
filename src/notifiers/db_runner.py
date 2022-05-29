
# def get_sleep_length(next_query):
#     pass
# from src.db import db
from datetime import datetime, timedelta
from time import sleep

# from src.db.db import engine
from src.models import QueryDB, session, DiscordSenderDB
from src.notifiers.db_query_runner import DBQueryRunner
from src.senders.discord_sender import DiscordSender


def get_loggers():
    logger_entries = session.query(DiscordSenderDB) \
        .filter(DiscordSenderDB.for_logging == True) \
        .all()
    return [DiscordSender(s.url, s.notify) for s in logger_entries]


def log(loggers: list[DiscordSender], message: str):
    for logger in loggers:
        logger.send_plain(message)


def run():  # TODO make class
    while True:
        # conn = engine.connect()
        # queries = list(conn.execute(select(QueryDB).order_by(QueryDB.next_runtime).limit(2)))

        loggers = get_loggers()
        log(loggers, f"Waking up at {datetime.utcnow()} UTC")

        print(50 * "=")
        queries = session.query(QueryDB)\
            .order_by(QueryDB.next_runtime)\
            .limit(2)
        first_query = queries[0]
        print(f"first_query: {first_query}")
        second_query = queries[1]
        print(f"second_query: {second_query}")
        current_datetime = datetime.utcnow()
        print(f"current_datetime: {current_datetime}")
        timediff = timedelta(0)
        if first_query.next_runtime < current_datetime:
            log(loggers, f"running query {first_query}")
            print(f"running query {first_query}")
            timediff = max(timedelta(0), second_query.next_runtime - current_datetime)
            print("run")
            query_runner = DBQueryRunner(first_query)
            query_runner.run()
            # for product in query_runner.run():
            #     # if exists
            #     pass

        else:
            log(loggers, f"waiting for query {first_query}")
            print(f"waiting for query {first_query}")
            timediff = first_query.next_runtime - current_datetime

        print("commiting")
        session.commit()

        print(f"sleeping for {timediff}")
        log(loggers, f"sleeping for {timediff}")
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
