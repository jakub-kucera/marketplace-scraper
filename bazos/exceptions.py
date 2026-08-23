class MarketplaceBlockedError(Exception):
    """Raised when the marketplace refuses the current egress IP.

    Not Bazos-specific despite only the two Bazos scrapers raising it today: the runner
    catches it generically and answers by rotating the IP and retrying, which is what
    Vinted and Sbazar will need too. See `ScrapeRunner._run_query_with_rotation`.

    403 is the only block status confirmed live on Bazos (nginx-level deny, path-scoped);
    the API scraper's 429 handling is defensive, so the message names both without
    claiming either.
    """

    def __init__(self, message: str = "Marketplace returned 403/429 for the current IP"):
        super().__init__(message)
