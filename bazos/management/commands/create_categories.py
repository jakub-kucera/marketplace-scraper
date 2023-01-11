import json
from time import sleep

from django.core.management.base import BaseCommand
import requests

from bazos.models import Section, Category


class Command(BaseCommand):
    help = "Create Bazos categories from sections"

    # def add_arguments(self, parser):
    #     parser.add_argument(
    #         "--path",
    #         help="Path of the file to import",
    #     )

    def handle(self, *args, **options):
        for section in Section.objects.all():
            url = f"https://www.bazos.cz/api/v1/categories.php?section={section.bazos_id}"
            r = requests.get(url)
            data = r.json()
            print(data)
            for category in data:
                Category.objects.create(
                    bazos_id=category["id"],
                    name=category["title"],
                    url=category["url"],
                    section=section,
                )
                print(category)
            sleep(5)
            # break
            # section.delete()