from typing import List

import yagmail

from src.sendables.sendable import Sendable
from src.senders.sender import Sender


class EmailSender(Sender):

    def __init__(self, sender: str, receiver: str, notify: bool = False):
        super().__init__(notify)
        self.sender = sender
        self.receiver = receiver

    def _format_product_message(self, sendable: Sendable) -> str:
        return sendable.message + '\n' + sendable.link

    def send_sendable(self, sendables: List[Sendable]):
        yag = yagmail.SMTP(self.sender)
        for s in sendables:
            # print(f"Sending {product.name=}")
            yag.send(
                to=self.receiver,
                subject=s.message,
                contents=self._format_product_message(s),
            )

    def send_plain(self, text: str):
        yag = yagmail.SMTP(self.sender)
        yag.send(
            to=self.receiver,
            subject=text,
            contents=text,
        )


# if __name__ == "__main__":
#     s = EmailSender(sender=SETTINGS.EMAIL_SENDER, receiver=SETTINGS.EMAIL_RECEIVER)
#     s.send_plain("This is a test")
