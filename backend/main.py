from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import random

app = FastAPI(title="VibeItUp API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Metric(BaseModel):
    label: str
    value: float
    delta: float
    unit: str

class Widget(BaseModel):
    id: str
    title: str
    value: str
    delta: float
    trend: List[float]
    icon: str

# Demo-Daten für futuristisches Dashboard
METRICS = [
    {"label": "Uptime", "value": 99.98, "delta": 0.12, "unit": "%"},
    {"label": "Latency", "value": 42, "delta": -8.5, "unit": "ms"},
    {"label": "Throughput", "value": 12840, "delta": 4.2, "unit": "req/s"},
    {"label": "Errors", "value": 0.3, "delta": -0.15, "unit": "%"},
]

WIDGETS = [
    {"id":"w1","title":"Active Nodes","value":"2.847","delta":12.5,"trend":[42,48,55,51,67,82,75,91,88,102,115,120],"icon":"cpu"},
    {"id":"w2","title":"Data Flow","value":"1.3 TB","delta":-2.1,"trend":[12,15,13,18,14,22,19,25,21,28,23,30],"icon":"database"},
    {"id":"w3","title":"Security Score","value":"98.6","delta":1.4,"trend":[85,87,89,91,90,93,95,94,96,97,98,99],"icon":"shield"},
    {"id":"w4","title":"Energy Usage","value":"342 kW","delta":5.3,"trend":[280,310,295,340,325,310,350,340,360,345,330,342],"icon":"zap"},
]

@app.get("/api/metrics", response_model=List[Metric])
def get_metrics():
    return [Metric(**m) for m in METRICS]

@app.get("/api/widgets", response_model=List[Widget])
def get_widgets():
    return [Widget(**w) for w in WIDGETS]

@app.get("/api/health")
def health():
    return {"status":"operational","service":"vibeitup-dashboard","timestamp":"2026-09-05T00:00:00"}
