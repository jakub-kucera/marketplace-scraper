from django.db import models


class FBUser(models.Model):
    phone_number = models.CharField(max_length=100)  # TODO phone number field
    facebook_id = models.CharField(max_length=100, unique=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50, null=True, blank=True)
    gender = models.CharField(max_length=10)  # TODO: enum
    municipality_of_residence = models.CharField(max_length=100)
    municipality_of_birth = models.CharField(max_length=100)
    relationship_status = models.CharField(max_length=30)  # TODO: enum
    occupation = models.CharField(max_length=100)
    email = models.EmailField(null=True, blank=True)
    date_of_birth = models.CharField(max_length=100)  # TODO: date

    def __str__(self):
        return f"{self.first_name} {self.last_name}"
