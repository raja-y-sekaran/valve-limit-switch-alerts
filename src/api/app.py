"""FastAPI service: send one valve's definition and its SOE records, get its strokes and operator alerts.

    uvicorn src.api.app:app --reload      # then open http://127.0.0.1:8000/docs
"""
from typing import List

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.alerts.rules import raw_alerts, shelve
from src.data.preprocess import prepare_events
from src.features.strokes import parse_strokes
from src.models.baseline import baselines

app = FastAPI(title="Valve limit-switch alerts", version="1.0",
              description="Stroke timing, trend, sticking and chatter alerts from DCS SOE records. Synthetic-data demo.")


class Valve(BaseModel):
    tag: str = Field(examples=["XV-1101"])
    service: str = Field("process on/off", description="'process on/off' or 'shutdown valve'")
    open_s: float = Field(gt=0, description="Nominal opening time, s")
    close_s: float = Field(gt=0, description="Nominal closing time, s")
    open_limit_s: float = Field(gt=0)
    close_limit_s: float = Field(gt=0)


class SoeRecord(BaseModel):
    timestamp: str = Field(examples=["2025-03-01T08:00:00.000"])
    point: str = Field(examples=["XV-1101.CMD"], description="<tag>.CMD, <tag>.ZSO or <tag>.ZSC")
    value: int = Field(ge=0, le=1)


class History(BaseModel):
    valve: Valve
    events: List[SoeRecord] = Field(description="The valve's SOE records in any order; the first weeks are used "
                                                "to learn its normal stroke time")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/alerts")
def alerts(h: History):
    if any(not e.point.startswith(h.valve.tag + ".") for e in h.events):
        raise HTTPException(422, f"every point must belong to {h.valve.tag}")
    reg = pd.DataFrame([dict(h.valve.model_dump(), strokes_per_day=0, breakaway_s=0)])
    ev = prepare_events(pd.DataFrame([e.model_dump() for e in h.events]))
    strokes, uncmd = parse_strokes(ev, reg)
    if strokes.empty:
        return dict(strokes=0, alerts=[])
    a = shelve(raw_alerts(strokes, uncmd, reg, baselines(strokes)))
    return dict(strokes=len(strokes), stroke_status=strokes.status.value_counts().to_dict(),
                alerts=[] if a.empty else a.assign(ts=a.ts.astype(str)).to_dict("records"))
