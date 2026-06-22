import pytest
from pydantic import ValidationError

from common.models import Priority, Status, Ticket


def test_valid_ticket_create():
    t = Ticket(
        priority="high", description="Printer down",
        requestingArea="Finance", reportedBy="jdoe",
    )
    assert t.priority is Priority.HIGH
    assert t.description == "Printer down"


def test_status_enum_values():
    assert {s.value for s in Status} == {"open", "in_progress", "resolved"}


def test_invalid_priority_rejected():
    with pytest.raises(ValidationError):
        Ticket(priority="urgent", description="x", requestingArea="IT", reportedBy="a")


def test_missing_field_rejected():
    with pytest.raises(ValidationError):
        Ticket(priority="low", description="x", requestingArea="IT")


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        Ticket(
            priority="low", description="x", requestingArea="IT",
            reportedBy="a", status="open",
        )


def test_blank_description_rejected():
    with pytest.raises(ValidationError):
        Ticket(priority="low", description="", requestingArea="IT", reportedBy="a")
