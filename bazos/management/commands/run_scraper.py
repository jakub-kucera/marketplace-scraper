import os

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Runs Bazos scraper in a loop"

    def handle(self, *args, **options):
        if not os.path.exists(SETTINGS.LOG_DIRECTORY_PATH):
            os.makedirs(SETTINGS.LOG_DIRECTORY_PATH)

        runner = BazosRunner()
        runner.run()

        # while True:
        #     try:
        #         runner = BazosRunner()
        #         runner.run()
        #     except Exception as e:
        #         current_time = strftime("%Y%m%d-%H%M%S")
        #         with open(f"{SETTINGS.LOG_DIRECTORY_PATH}{current_time}", "w") as log_file:
        #             log_file.write(str(e))
        #             log_file.write(traceback.format_exc())
