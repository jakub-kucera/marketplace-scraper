import logging
import os
import traceback
from time import strftime, sleep

from django.conf import settings
from django.core.management.base import BaseCommand

from bazos.scraping.bazos_runner import BazosRunner

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Runs Bazos scraper in a loop"

    def add_arguments(self, parser):
        parser.add_argument(
            "--unsafe",
            action="store_true",
            help="With this options, the scraper will stop running if an exception is raised",
        )


    def handle(self, *args, **options):
        if not os.path.exists(settings.LOG_DIRECTORY_PATH):
            os.makedirs(settings.LOG_DIRECTORY_PATH)

        if options["unsafe"]:
            runner = BazosRunner()
            runner.run()
            return

        while True:
            try:
                runner = BazosRunner()
                runner.run()
            except Exception as e:
                current_time = strftime("%Y%m%d-%H%M%S")
                logger.exception("BazosRunner crashed: %s", e)
                with open(f"{settings.LOG_DIRECTORY_PATH}{current_time}", "w") as log_file:
                    log_file.write(str(e))
                    log_file.write(traceback.format_exc())
                print("Sleeping for 60 seconds")
                sleep(60)
