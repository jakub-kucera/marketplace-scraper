from abc import ABC, abstractmethod
from typing import List, Any

from bazos.mixins import SendableMixin


class Sender(ABC):
    def __init__(self, notify: bool = False):
        self.notify = notify

    @staticmethod
    def wrap_multi_line(message: str) -> str:
        return "```" + message + "```"

    @staticmethod
    def wrap_single_line(message: str) -> str:
        return "`" + message + "`"

    @abstractmethod
    def _format_product_message(self, sendable: SendableMixin) -> str:
        pass

    @abstractmethod
    def send_sendable(self, sendables: List[SendableMixin]):
        pass

    @abstractmethod
    def send_plain(self, text: str):
        pass
