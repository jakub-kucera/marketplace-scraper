class BazosBlacklistedError(Exception):
    """Raised when the current public IP is blacklisted on Bazos."""

    def __init__(self, message: str = "Bazos returned 403/429 for the current IP"):
        super().__init__(message)
