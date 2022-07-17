import os
import traceback
from time import strftime

from settings import SETTINGS
from src.notifiers.bazos_runner import BazosRunner


def main():
    # create log directory if not exists
    if not os.path.exists(SETTINGS.LOG_DIRECTORY_PATH):
        os.makedirs(SETTINGS.LOG_DIRECTORY_PATH)

    while True:
        try:
            runner = BazosRunner()
            runner.run()
        except Exception as e:
            current_time = strftime("%Y%m%d-%H%M%S")
            with open(f"{SETTINGS.LOG_DIRECTORY_PATH}{current_time}", "w") as log_file:
                log_file.write(str(e))
                log_file.write(traceback.format_exc())

# from data_import import import_basic_data


if __name__ == "__main__":
    main()
