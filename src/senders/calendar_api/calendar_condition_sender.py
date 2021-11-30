from typing import List, Dict, Iterator, Any, Tuple

from src.sendables.sendable import Sendable
from src.senders.console_sender import ConsoleSender
from src.senders.sender import Sender

import datetime
import os.path

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']


class CalendarConditionSender(Sender):
    def __init__(self, sender: Sender, calendar_event_names: list[str], notify: bool = False):
        super().__init__(notify)
        self.sender = sender
        self.calendar_event_names = calendar_event_names
        self.service = None
        self.setup_api()

    def setup_api(self):
        creds = None

        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            with open('token.json', 'w') as token:
                token.write(creds.to_json())

        self.service = build('calendar', 'v3', credentials=creds)

    def can_send(self) -> bool:
        if self.service is None:
            self.setup_api()

        events_result = self.service.events().list(calendarId='primary',
                                                   timeMin=datetime.datetime.utcnow().isoformat() + 'Z',
                                                   maxResults=1, singleEvents=True,
                                                   orderBy='startTime').execute()
        events = events_result.get('items', [])
        if not events:
            return False
        event = events[0]

        # extract dates
        event_start_str: str = event['start'].get('dateTime', event['start'].get('date'))
        event_start = datetime.datetime.strptime(event_start_str, '%Y-%m-%dT%H:%M:%S%z')
        now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)

        print(f"Already started: {event_start <= now}")
        print(f"Same event name: {event['summary'] in self.calendar_event_names}")
        return (event_start <= now) and \
               (event['summary'] in self.calendar_event_names)

    def send_sendable(self, sendables: List[Sendable]):
        if self.can_send():
            self.sender.send_sendable(sendables)

    def send_plain(self, text: str):
        if self.can_send():
            self.sender.send_plain(text)

    def _format_product_message(self, sendable: Sendable) -> str:
        pass


def main1():
    calendar_sender = CalendarConditionSender(ConsoleSender(), ["WORK", "test"])
    for i in range(1000):
        calendar_sender.send_plain(f"testicek #{i}")


if __name__ == '__main__':
    main1()
