"""Seed `MarketplaceCategory` with Vinted's category tree.

Idempotent and safe to re-run: one HTTP request, `update_or_create` keyed on
(marketplace, external_id), and nothing is ever deleted. See
docs/backlog/VINTED_REWRITE.md §2.2.
"""
import logging
import re
from typing import Any, Iterator

from django.core.management.base import BaseCommand
from django.db import transaction

from bazos.const import VINTED_BASE_URL
from bazos.models import MarketplaceCategory, Marketplace, Query
from bazos.scraping.vinted import flight
from bazos.scraping.vinted.client import VintedClient

logger = logging.getLogger(__name__)

#: Any catalog page ships the whole tree; the search text is irrelevant.
SEED_PATH = "/catalog"
SEED_PARAMS = (("search_text", "a"),)

_SLUG = re.compile(r"/catalog/(\d+)-([a-z0-9-]+)")


def _slug_of(node: dict[str, Any]) -> str:
    url = node.get("url") or node.get("customUrl") or ""
    match = _SLUG.match(url) if isinstance(url, str) else None
    return f"{match.group(1)}-{match.group(2)}" if match else ""


def walk(nodes: Any, parent_id: int | None = None) -> Iterator[tuple[int, str, str, int | None]]:
    """Yield `(id, title, slug, parent_id)` for every node in a `catalogs` array."""
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id, title = node.get("id"), node.get("title")
        if not isinstance(node_id, int) or not isinstance(title, str) or not title:
            continue
        yield node_id, title, _slug_of(node), parent_id
        yield from walk(node.get("catalogs"), node_id)


def collect(payload: str) -> dict[int, tuple[str, str, int | None]]:
    """Every catalog node in the payload, with parents resolved from structure.

    ⚠️ The tree is **not** shipped as one array. `"catalogs":[…]` occurs ~2,100 times,
    each holding a subtree, and the first occurrence is a mid-tree slice — seeding from it
    alone yields ~270 apparel nodes and silently misses all of Electronics. So every
    occurrence is walked and the results unioned.

    A node is seen many times over; a sighting that knows the parent wins over one that
    does not, which is what turns the union back into a tree (9 roots, measured).
    """
    found: dict[int, tuple[str, str, int | None]] = {}
    for array in flight.iter_values(payload, "catalogs"):
        for node_id, title, slug, parent_id in walk(array):
            existing = found.get(node_id)
            if existing is None or (existing[2] is None and parent_id is not None):
                found[node_id] = (title, slug, parent_id)
    return found


class Command(BaseCommand):
    help = "Sync Vinted's category tree into MarketplaceCategory (idempotent, one request)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-url",
            default=VINTED_BASE_URL,
            help="Vinted domain to read the tree from. The taxonomy is shared across "
                 "domains; only the labels are localised.",
        )

    def handle(self, *args, **options):
        client = VintedClient(options["base_url"])
        payload = flight.decode(client.get_flight(SEED_PATH, SEED_PARAMS))
        nodes = collect(payload)

        if not nodes:
            # No exception and no partial write: an empty parse means the page shape
            # changed or we were served an interstitial, and quietly seeding nothing
            # would look like success.
            raise RuntimeError(
                "Vinted returned no catalog nodes — the page shape likely changed. "
                "Nothing was written; see docs/research/marketplaces/VINTED.md §2."
            )

        created, updated = self._sync(nodes)
        self._warn_about_missing(nodes)

        logger.info("Vinted catalogs synced: %d created, %d updated", created, updated)
        self.stdout.write(f"Vinted catalogs synced: {created} created, {updated} updated")

    @transaction.atomic
    def _sync(self, nodes: dict[int, tuple[str, str, int | None]]) -> tuple[int, int]:
        """Two passes: rows first, then parents.

        A single pass would need the parent row to exist before its child, which the
        payload does not guarantee — the union in `collect` has no ordering. Writing
        parents afterwards sidesteps it entirely.
        """
        created = updated = 0
        for external_id, (title, slug, _) in nodes.items():
            _, was_created = MarketplaceCategory.objects.update_or_create(
                marketplace=Marketplace.VINTED,
                external_id=str(external_id),
                defaults={"name": title[:120], "slug": slug[:160]},
            )
            created += was_created
            updated += not was_created

        by_external = {
            int(row.external_id): row
            for row in MarketplaceCategory.objects.filter(marketplace=Marketplace.VINTED)
            if row.external_id.isdigit()
        }
        to_update = []
        for external_id, (_, _, parent_external_id) in nodes.items():
            row = by_external.get(external_id)
            parent = by_external.get(parent_external_id) if parent_external_id else None
            if row is not None and row.parent_id != (parent.pk if parent else None):
                row.parent = parent
                to_update.append(row)
        if to_update:
            MarketplaceCategory.objects.bulk_update(to_update, ["parent"], batch_size=500)
        return created, updated

    def _warn_about_missing(self, nodes: dict[int, tuple[str, str, int | None]]) -> None:
        """Report retired nodes — never delete them.

        Deleting would strand the ids sitting in `Query.extra_params`, and not stranding
        them is the entire reason this is a lookup table rather than a `Query` FK
        (see MarketplaceCategory's docstring). A retired id degrades to "returns
        nothing", which is recoverable; a deleted row plus a silently-widened query is
        not.
        """
        live = {str(external_id) for external_id in nodes}
        stale = set(
            MarketplaceCategory.objects
            .filter(marketplace=Marketplace.VINTED)
            .exclude(external_id__in=live)
            .values_list("external_id", flat=True)
        )
        if not stale:
            return

        logger.warning(
            "Vinted no longer lists %d catalog node(s) kept in the DB: %s",
            len(stale), sorted(stale),
        )
        for query in Query.objects.filter(marketplace=Marketplace.VINTED):
            referenced = {str(cid) for cid in (query.extra_params or {}).get("catalog_ids", [])}
            overlap = referenced & stale
            if overlap:
                logger.warning(
                    "Query %s (pk=%s) filters on retired Vinted catalog id(s) %s — "
                    "it will return nothing for those until they are changed.",
                    query, query.pk, sorted(overlap),
                )
