"""FastAPI endpoints for the Execution layer."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from artha.execution.killswitch import kill_switch
from artha.execution.schemas import KillSwitchStatus

router = APIRouter(prefix="/execution", tags=["execution"])


@router.get("/killswitch", response_model=KillSwitchStatus)
async def get_killswitch_status():
    return kill_switch.status()


@router.post("/killswitch/activate", response_model=KillSwitchStatus)
async def activate_killswitch(by: str = "api"):
    kill_switch.activate(by=by)
    return kill_switch.status()


@router.post("/killswitch/deactivate", response_model=KillSwitchStatus)
async def deactivate_killswitch(by: str = "api"):
    kill_switch.deactivate(by=by)
    return kill_switch.status()
