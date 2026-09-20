from django.db import models
from django_extensions.db.models import TimeStampedModel


class Discord(TimeStampedModel):
    channel_name = models.CharField(max_length=120)
    url = models.URLField(max_length=200, help_text="Webhook URL", unique=True)
    notify = models.BooleanField(default=False, help_text="Notify/Ping on new Ad")
    for_logging = models.BooleanField(default=False, db_index=True)
    for_summary = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "Post the end-of-pass scrape digest here. Never pings, whatever `notify` says — "
            "it fires once per pass. Best kept off the `for_logging` channel."
        ),
    )

    for_daily_digest = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "Post the 13:00 daily digest here — embeds with charts, once a day. Never pings, "
            "whatever `notify` says. Best kept off `for_summary`: that one fires ~32x a day and "
            "would bury the digest within minutes of it arriving."
        ),
    )

    class Meta:
        # "Discords" is what Django pluralises the model name into, and the sidebar and
        # app list both show it. These are webhook targets, so name them that.
        verbose_name = "Discord channel"
        verbose_name_plural = "Discord channels"

    def __str__(self):
        return f"{self.channel_name} | notify={self.notify}"
