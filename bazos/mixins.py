from django.db.models import Model


# TODO rename
class SendableMixin(Model):
    class Meta:
        abstract = True

    @property
    def message(self):
        raise NotImplementedError

    @property
    def link(self):
        raise NotImplementedError

