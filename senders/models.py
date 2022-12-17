from django.db import models
from django_extensions.db.models import TimeStampedModel


class Discord(TimeStampedModel):
    channel_name = models.CharField(max_length=120)
    url = models.URLField(max_length=200, help_text="Webhook URL", unique=True)
    notify = models.BooleanField(default=False, help_text="Notify/Ping on new Ad")
    for_logging = models.BooleanField(default=False, db_index=True)

    def __str__(self):
        return f"{self.channel_name} | notify={self.notify}"
