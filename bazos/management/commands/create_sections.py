import json

from django.core.management.base import BaseCommand

from bazos.models import Section

# SECTIONS_FILE = 'categories/sections.json'
SECTIONS_FILE = 'bazos/management/commands/categories/sections.json'


class Command(BaseCommand):
    help = "Create Bazos sections"

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            help="Path of the file to import",
        )

    def handle(self, *args, **options):
        # requests.get('https://www.bazos.cz/api/v1/sections.php')
        with open(SECTIONS_FILE, 'r') as f:
            sections = json.load(f)
            for section in sections:
                bazos_id = section['id']
                name = section['title']
                url = section['url']
                Section.objects.create(bazos_id=bazos_id, name=name, url=url)
