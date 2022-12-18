from abc import ABC, abstractmethod


class Sendable(ABC):

    @property
    @abstractmethod
    def message(self):
        pass

    @property
    @abstractmethod
    def link(self):
        pass
