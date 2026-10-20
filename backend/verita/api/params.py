"""Shared path parameters.

Primary keys are 32-bit integers on PostgreSQL; bounding path IDs to that range turns an
oversized ID into a 422 instead of a driver overflow (a 500 found by contract fuzzing).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Path

MAX_ID = 2_147_483_647

AlertId = Annotated[int, Path(ge=1, le=MAX_ID, description="Alert ID")]
CaseId = Annotated[int, Path(ge=1, le=MAX_ID, description="Case ID")]
JobId = Annotated[int, Path(ge=1, le=MAX_ID, description="Job ID")]
