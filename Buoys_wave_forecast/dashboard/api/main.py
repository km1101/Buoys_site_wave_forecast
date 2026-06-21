import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg2 import OperationalError

from .db import fetch_all

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

FORECAST_PARAMETERS = [
    {"id": "wave_height", "label": "Wave height (m)", "group": "Combined"},
    {"id": "wave_direction", "label": "Wave direction (°)", "group": "Combined"},
    {"id": "wave_period", "label": "Wave period (s)", "group": "Combined"},
    {"id": "wave_peak_period", "label": "Wave peak period (s)", "group": "Combined"},
    {"id": "wind_wave_height", "label": "Wind wave height (m)", "group": "Wind sea"},
    {"id": "wind_wave_direction", "label": "Wind wave direction (°)", "group": "Wind sea"},
    {"id": "wind_wave_period", "label": "Wind wave period (s)", "group": "Wind sea"},
    {"id": "wind_wave_peak_period", "label": "Wind wave peak period (s)", "group": "Wind sea"},
    {"id": "swell_wave_height", "label": "Swell height (m)", "group": "Swell"},
    {"id": "swell_wave_direction", "label": "Swell direction (°)", "group": "Swell"},
    {"id": "swell_wave_period", "label": "Swell period (s)", "group": "Swell"},
    {"id": "swell_wave_peak_period", "label": "Swell peak period (s)", "group": "Swell"},
    {"id": "sea_surface_temperature", "label": "Sea surface temp (°C)", "group": "Ocean"},
    {"id": "ocean_current_velocity", "label": "Current velocity (m/s)", "group": "Ocean"},
    {"id": "ocean_current_direction", "label": "Current direction (°)", "group": "Ocean"},
    {"id": "sea_level_height_msl", "label": "Sea level (m MSL)", "group": "Ocean"},
]

ALLOWED_PARAMETER_IDS = {p["id"] for p in FORECAST_PARAMETERS}

app = FastAPI(title="Marine Wave Forecast API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ValueError)
def config_error_handler(_, exc: ValueError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(OperationalError)
def database_error_handler(_, exc: OperationalError):
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "Database connection failed. Check DATABASE_URL in dashboard/.env "
                f"({exc})"
            )
        },
    )


def _split_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [v.strip() for v in value.split(",") if v.strip()]
    return items or None


def _parse_boundary(value: str, *, end_of_day: bool) -> datetime:
    """Parse a user-supplied ISO date or datetime string into an aware UTC datetime."""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date: '{value}'. Use YYYY-MM-DD.")
    date_only = len(value.strip()) <= 10
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if date_only and end_of_day:
        dt = dt + timedelta(hours=23, minutes=59, seconds=59)
    return dt


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "marine-wave-forecast-api"}


@app.get("/api/parameters")
def list_parameters():
    return FORECAST_PARAMETERS


@app.get("/api/sites")
def list_sites():
    rows = fetch_all("""
        SELECT site_id, site_name, latitude, longitude
        FROM sites
        WHERE active = true
        ORDER BY site_name
    """)
    for row in rows:
        row["site_id"] = str(row["site_id"])
    return rows


@app.get("/api/models")
def list_models():
    rows = fetch_all("""
        SELECT model_id, model_name, provider, description
        FROM models
        WHERE active = true
        ORDER BY model_name
    """)
    for row in rows:
        row["model_id"] = str(row["model_id"])
    return rows


@app.get("/api/forecast/latest")
def latest_forecast_by_site(
    site_id: str = Query(..., description="One or more comma-separated site UUIDs"),
):
    site_ids = _split_csv(site_id)
    if not site_ids:
        raise HTTPException(status_code=400, detail="site_id is required")

    rows = fetch_all("""
        WITH ranked AS (
            SELECT
                s.site_id,
                s.site_name,
                m.model_name,
                m.model_id,
                wf.forecast_time,
                wf.wave_height,
                wf.swell_wave_height,
                ROW_NUMBER() OVER (
                    PARTITION BY wf.site_id, m.model_id
                    ORDER BY wf.forecast_time DESC
                ) AS rn
            FROM wave_forecast wf
            JOIN models m ON m.model_id = wf.model_id
            JOIN sites s ON s.site_id = wf.site_id
            WHERE wf.site_id = ANY(%s)
              AND wf.forecast_time <= now()
        )
        SELECT
            site_id,
            site_name,
            model_name,
            model_id,
            forecast_time AS latest_forecast_time,
            wave_height,
            swell_wave_height
        FROM ranked
        WHERE rn = 1
        ORDER BY site_name, model_name
    """, (site_ids,))

    for row in rows:
        row["site_id"] = str(row["site_id"])
        row["model_id"] = str(row["model_id"])
        if row.get("latest_forecast_time"):
            row["latest_forecast_time"] = row["latest_forecast_time"].isoformat()
    return rows


@app.get("/api/forecast")
def get_forecast(
    site_id: str = Query(..., description="One or more comma-separated site UUIDs"),
    model_id: str | None = Query(None, description="One or more comma-separated model UUIDs (omit for all)"),
    parameter: str | None = Query(None, description="Single forecast variable (legacy)"),
    parameters: str | None = Query(None, description="Comma-separated forecast variables"),
    days_ahead: int | None = Query(None, ge=1, le=14, description="Forecast horizon in days from now"),
    start_date: str | None = Query(None, description="ISO date/datetime, inclusive range start (overrides days_ahead)"),
    end_date: str | None = Query(None, description="ISO date/datetime, inclusive range end (overrides days_ahead)"),
):
    site_ids = _split_csv(site_id)
    if not site_ids:
        raise HTTPException(status_code=400, detail="site_id is required")
    model_ids = _split_csv(model_id)

    if parameters:
        param_list = [p.strip() for p in parameters.split(",") if p.strip()]
    elif parameter:
        param_list = [parameter.strip()]
    else:
        param_list = ["wave_height"]

    for param in param_list:
        if param not in ALLOWED_PARAMETER_IDS:
            raise HTTPException(status_code=400, detail=f"Unknown parameter: {param}")

    if start_date or end_date:
        start = _parse_boundary(start_date, end_of_day=False) if start_date else datetime.now(timezone.utc)
        end = _parse_boundary(end_date, end_of_day=True) if end_date else start + timedelta(days=7)
        if end < start:
            raise HTTPException(status_code=400, detail="end_date must be on or after start_date")
    else:
        days_ahead = days_ahead or 7
        start = datetime.now(timezone.utc)
        end = start + timedelta(days=days_ahead)

    param_columns = ", ".join(f"wf.{p}" for p in param_list)
    label_by_id = {p["id"]: p["label"] for p in FORECAST_PARAMETERS}

    query_params: list = [site_ids, start, end]
    model_filter_sql = ""
    if model_ids:
        model_filter_sql = "AND wf.model_id = ANY(%s)"
        query_params.append(model_ids)

    rows = fetch_all(f"""
        SELECT
            wf.forecast_time,
            wf.site_id,
            s.site_name,
            wf.model_id,
            m.model_name,
            {param_columns}
        FROM wave_forecast wf
        JOIN models m ON m.model_id = wf.model_id
        JOIN sites s ON s.site_id = wf.site_id
        WHERE wf.site_id = ANY(%s)
          AND wf.forecast_time >= %s
          AND wf.forecast_time <= %s
          {model_filter_sql}
        ORDER BY wf.forecast_time, s.site_name, m.model_name
    """, tuple(query_params))

    series = []
    for row in rows:
        forecast_time = row["forecast_time"].isoformat() if row.get("forecast_time") else None
        site_name = row.get("site_name")
        site_id_val = str(row["site_id"]) if row.get("site_id") else None
        model_name = row.get("model_name")
        model_id_val = str(row["model_id"]) if row.get("model_id") else None
        for param in param_list:
            value = row.get(param)
            series.append({
                "forecast_time": forecast_time,
                "site_id": site_id_val,
                "site_name": site_name,
                "model_id": model_id_val,
                "model_name": model_name,
                "parameter": param,
                "parameter_label": label_by_id.get(param, param),
                "value": None if value is None else float(value),
            })

    return {
        "site_ids": site_ids,
        "model_ids": model_ids,
        "parameters": param_list,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "series": series,
    }


@app.get("/")
def serve_dashboard():
    index = STATIC_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return HTMLResponse(
        content=index.read_text(encoding="utf-8"),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
