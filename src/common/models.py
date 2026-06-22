
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field

class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class Status(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"

class Ticket(BaseModel):

    model_config = ConfigDict(extra="forbid") 
    priority: Priority
    description: str = Field(min_length=1, max_length=2000)
    requestingArea: str = Field(min_length=1, max_length=200)
    reportedBy: str = Field(min_length=1, max_length=200)
