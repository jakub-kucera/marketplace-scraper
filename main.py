import asyncio
import os
import traceback
from time import strftime
from typing import List

from src.config import get_new_config
from settings import SETTINGS
from src.notifiers.notifier import Notifier
from src.runner import Runner


def main():
    # create log file if not exists
    if not os.path.exists(SETTINGS.LOG_DIRECTORY_PATH):
        os.makedirs(SETTINGS.LOG_DIRECTORY_PATH)

    while True:
        try:
            notifiers: List[Notifier] = get_new_config()
            Runner.run(notifiers)
        except Exception as e:
            current_time = strftime("%Y%m%d-%H%M%S")
            with open(f"{SETTINGS.LOG_DIRECTORY_PATH}{current_time}", "w") as log_file:
                log_file.write(str(e))
                log_file.write(traceback.format_exc())


if __name__ == "__main__":
    main()
