from common.repository import TicketRepository


def _ticket(tid, created_at, status="open"):
    return {
        "id": tid, "createdAt": created_at, "status": status,
        "priority": "low", "description": "d",
        "requestingArea": "IT", "reportedBy": "a",
    }


def test_put_and_get(aws):
    repo = TicketRepository()
    t = _ticket("t1", "2026-01-01T00:00:00+00:00")
    repo.put(t)
    assert repo.get("t1") == t


def test_get_missing_returns_none(aws):
    repo = TicketRepository()
    assert repo.get("nope") is None


def test_query_by_status_oldest_first(aws):
    repo = TicketRepository()
    for tid, ts in [("t0", "2026-01-03"), ("t1", "2026-01-01"), ("t2", "2026-01-02")]:
        repo.put(_ticket(tid, ts))
    items, cursor = repo.query_by_status("open", limit=10)
    assert [i["createdAt"] for i in items] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert cursor is None


def test_query_pagination(aws):
    repo = TicketRepository()
    for i in range(3):
        repo.put(_ticket(f"t{i}", f"2026-01-0{i + 1}"))
    first, cursor = repo.query_by_status("open", limit=2)
    assert len(first) == 2
    assert cursor is not None
    second, cursor2 = repo.query_by_status("open", limit=2, cursor=cursor)
    assert len(second) == 1
    assert cursor2 is None
