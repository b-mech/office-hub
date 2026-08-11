from __future__ import annotations

import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

from app.modules.costbook.models import PurchaseOrder  # noqa: F401 - registers ORM target
from app.models.core import Development
from app.models.core import DevelopmentType
from app.services.developments import DevelopmentService
from app.services.developments import municipality_display_name
from app.services.developments import municipality_key
from app.services.developments import normalize_development_name


class DevelopmentServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_development_name_normalization_and_rm_aliases(self) -> None:
        self.assertEqual("forest grove estates", normalize_development_name("  Forest   Grove Estates "))
        self.assertEqual(municipality_key("RM of West St. Paul"), municipality_key("West St Paul"))
        self.assertEqual("RM of Springfield", municipality_display_name("Springfield"))
        self.assertEqual("RM of Headingley", municipality_display_name("RM of Headingley"))

    async def test_cycle_prevention_rejects_descendant_as_parent(self) -> None:
        root_id = uuid4()
        child_id = uuid4()
        grandchild_id = uuid4()
        db = AsyncMock()
        developments = {
            grandchild_id: Development(id=grandchild_id, parent_id=child_id),
            child_id: Development(id=child_id, parent_id=root_id),
        }
        db.get.side_effect = lambda _model, record_id: developments.get(record_id)
        service = DevelopmentService(db)

        with self.assertRaisesRegex(ValueError, "cannot contain a cycle"):
            await service._assert_not_descendant(root_id, grandchild_id)

    async def test_community_requires_municipality_parent(self) -> None:
        org_id = uuid4()
        parent_id = uuid4()
        db = AsyncMock()
        db.get.return_value = Development(
            id=parent_id,
            org_id=org_id,
            development_type=DevelopmentType.SUBDIVISION,
        )
        service = DevelopmentService(db)

        with self.assertRaisesRegex(ValueError, "Communities must be children of municipalities"):
            await service._validate_parent(
                org_id=org_id,
                parent_id=parent_id,
                development_type=DevelopmentType.COMMUNITY,
            )


if __name__ == "__main__":
    unittest.main()
