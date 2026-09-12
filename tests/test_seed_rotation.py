from __future__ import annotations

from src.config import next_run_seed_queries
from src.db.mongo_client import ReviewQueueStore
from tests.conftest import FakeMongoClient, FakeReviewCollection

EVERGREEN = [
    "Akwa Ibom news this week",
    "Uyo Nigeria culture",
    "Akwa Ibom state history",
]
LGAS = ["Uyo", "Ikot Ekpene", "Oron", "Eket"]


def _store() -> ReviewQueueStore:
    return ReviewQueueStore(
        uri="mongodb://localhost:27017",
        db_name="akisok_test",
        client=FakeMongoClient(FakeReviewCollection()),
    )


def test_lga_rotation_advances_and_wraps() -> None:
    mongo = _store()

    first = next_run_seed_queries(
        mongo,
        evergreen=EVERGREEN,
        lga_names=LGAS,
        rotation_size=3,
    )
    assert first[:3] == EVERGREEN
    assert first[3:] == ["Uyo Akwa Ibom", "Ikot Ekpene Akwa Ibom", "Oron Akwa Ibom"]
    assert mongo.get_lga_rotation_index() == 3

    second = next_run_seed_queries(
        mongo,
        evergreen=EVERGREEN,
        lga_names=LGAS,
        rotation_size=3,
    )
    assert second[:3] == EVERGREEN
    assert second[3:] == ["Eket Akwa Ibom", "Uyo Akwa Ibom", "Ikot Ekpene Akwa Ibom"]
    assert mongo.get_lga_rotation_index() == 2

    third = next_run_seed_queries(
        mongo,
        evergreen=EVERGREEN,
        lga_names=LGAS,
        rotation_size=3,
    )
    assert third[:3] == EVERGREEN
    assert third[3:] == ["Oron Akwa Ibom", "Eket Akwa Ibom", "Uyo Akwa Ibom"]
    assert mongo.get_lga_rotation_index() == 1
    assert all(query in third for query in EVERGREEN)
