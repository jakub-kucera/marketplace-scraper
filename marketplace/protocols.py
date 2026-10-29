"""Shared structural protocols for the sender pipeline."""
from typing import Protocol


class Sendable(Protocol):
    """Any object that can be formatted and sent by a Sender.

    :class:`bazos.models.Ad` already implements both properties — no changes
    to the model are needed. This Protocol replaces the old
    ``SendableMixin`` abstract base class.
    """

    @property
    def message(self) -> str: ...

    @property
    def link(self) -> str: ...
