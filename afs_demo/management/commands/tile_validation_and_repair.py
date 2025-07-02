"""
ARCHES - a program developed to inventory and manage immovable cultural heritage.
Copyright (C) 2013 J. Paul Getty Trust and World Monuments Fund

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.
"""
from django.core.management.base import BaseCommand
from arches.app.models.tile import Tile
from arches.app.models.models import Node
from arches.app.models.tile import TileValidationError



class Command(BaseCommand):
    """
    Validate and optionally repair tiles loaded via the database
    """

    def add_arguments(self, parser):

        parser.add_argument("-r", "--repair", action="store_true", dest="repair", help="'true' if you would like this script to attempt to repair invalid tiles ")
        parser.add_argument("-na", "--nodegroup_aliases", action="store", dest="nodegroups", help="nodegroup aliases of tiles to validate")

    def handle(self, *args, **options):
        self.validate(options["repair"], options["nodegroups"])

    def repair(self, range):
        start = f"{int(range[0]):05}"
        end = f"{int(range[1]):05}"
        return f"{start}/{end}" 

    def validate(self, repair, nodegroups):
        nodegroup_ids = Node.objects.filter(alias__in=nodegroups.split()).values_list("nodeid", flat=True)
        if nodegroup_ids:
            tiles = Tile.objects.filter(nodegroup_id__in=nodegroup_ids)
        else:
            tiles = Tile.objects.all()
        print(len(tiles))
        for tile in tiles:
            try:
                tile.validate(errors=[], raise_early=False)
            except TileValidationError:
                range = tile.data["abbcf7ce-5223-11f0-a2a8-020539808477"].split("/")
                repaired = self.repair(range)
                tile.data["abbcf7ce-5223-11f0-a2a8-020539808477"] = repaired
                tile.save()
        print("repair complete")
