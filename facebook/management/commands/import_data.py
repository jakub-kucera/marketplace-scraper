
from django.core.management.base import BaseCommand

from facebook.models import FBUser


class Command(BaseCommand):
    help = "Imports Facebook user data from a file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            help="Path of the file to import",
        )

    def handle(self, *args, **options):
        path = options["path"]
        print(path)

        FBUser.objects.all().delete()

        with open(path) as f:
            # reader = csv.reader(f, delimiter=":")
            # for row in reader:
            for line in f:
                # reader = csv.reader(line, delimiter=":")
                row = line.split(sep=':')

                if FBUser.objects.filter(facebook_id=row[1]).count() > 0:
                    self.stdout.write(f"Existing user: {row}")
                    continue

                user = FBUser(
                    phone_number=row[0],
                    facebook_id=row[1],
                    first_name=row[2],
                    last_name=row[3],
                    gender=row[4],
                    municipality_of_residence=row[5],
                    municipality_of_birth=row[6],
                    relationship_status=row[7],
                    occupation=row[8],
                    email=row[12],
                    date_of_birth=row[13]
                )
                user.save()
