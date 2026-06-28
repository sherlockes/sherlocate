from fastapi import FastAPI, Request, Query, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from typing import Optional, Dict, Any
from datetime import datetime
import logging
import os
import json

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Sherlocate")

# Parse allowed devices and their passwords from environment variable
# Format: ALLOWED_DEVICES=device1:pass1,device2:pass2,...
allowed_devices_env = os.getenv("ALLOWED_DEVICES", "")
ALLOWED_DEVICES_ORDER = []
DEVICE_PASSWORDS = {}

if allowed_devices_env:
    for entry in allowed_devices_env.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            d_id, d_pass = entry.split(":", 1)
            d_id = d_id.strip()
            d_pass = d_pass.strip()
            ALLOWED_DEVICES_ORDER.append(d_id)
            DEVICE_PASSWORDS[d_id] = d_pass
        else:
            d_id = entry
            ALLOWED_DEVICES_ORDER.append(d_id)

ALLOWED_DEVICES = set(ALLOWED_DEVICES_ORDER)

if ALLOWED_DEVICES:
    logger.info(f"Device authorization active. Allowed devices: {ALLOWED_DEVICES_ORDER}")
    logger.info(f"Loaded {len(DEVICE_PASSWORDS)} device-specific passwords.")
else:
    logger.info("Device authorization inactive. All device IDs are allowed.")

# HTTP Basic Security setup (auto_error=False makes authentication optional)
security = HTTPBasic(auto_error=False)

def verify_credentials(request: Request, credentials: Optional[HTTPBasicCredentials] = Depends(security)):
    # Extract device_id from path parameters if present
    device_id = request.path_params.get("device_id")
    required_password = DEVICE_PASSWORDS.get(str(device_id)) if device_id else None
    
    # If no password is set in the environment for this device, allow public access
    if not required_password:
        return "anonymous"
        
    # If a password is set, enforce authentication
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Basic"},
        )
        
    if credentials.password != required_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

app = FastAPI(
    title="Sherlocate API",
    description="A self-hosted location tracking server designed for Traccar Client",
    version="1.0.0"
)

# Enable CORS for convenience
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Jinja2 Templates
templates = Jinja2Templates(directory="templates")

# Global in-memory storage for device locations and history trail
# Key: device_id (string), Value: dictionary of device metadata and location
device_locations: Dict[str, Dict[str, Any]] = {}
device_history: Dict[str, list] = {}

# Pre-populate with allowed devices from ALLOWED_DEVICES whitelist (preserving original order)
for d_id in ALLOWED_DEVICES_ORDER:
    device_locations[str(d_id)] = {
        "id": str(d_id),
        "lat": 40.416775,
        "lon": -3.703790,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "hdop": None,
        "altitude": None,
        "speed": None,
        "battery": None,
        "last_seen": "1970-01-01T00:00:00.000000Z"
    }
    device_history[str(d_id)] = []

DATA_DIR = "/app/data"
LOCATIONS_FILE = os.path.join(DATA_DIR, "device_locations.json")
HISTORY_FILE = os.path.join(DATA_DIR, "device_history.json")

def init_persistent_storage():
    os.makedirs(DATA_DIR, exist_ok=True)
    global device_locations, device_history
    
    if os.path.exists(LOCATIONS_FILE):
        try:
            with open(LOCATIONS_FILE, "r") as f:
                loaded = json.load(f)
                for k, v in loaded.items():
                    device_locations[k] = v
            logger.info("Loaded persistent device locations from disk.")
        except Exception as e:
            logger.error(f"Error loading device locations: {e}")
            
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                loaded = json.load(f)
                for k, v in loaded.items():
                    device_history[k] = v
            logger.info("Loaded persistent device history from disk.")
        except Exception as e:
            logger.error(f"Error loading device history: {e}")

def save_persistent_locations():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        temp_file = LOCATIONS_FILE + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(device_locations, f, indent=2)
        os.replace(temp_file, LOCATIONS_FILE)
    except Exception as e:
        logger.error(f"Error saving device locations: {e}")

def save_persistent_history():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        temp_file = HISTORY_FILE + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(device_history, f, indent=2)
        os.replace(temp_file, HISTORY_FILE)
    except Exception as e:
        logger.error(f"Error saving device history: {e}")

# Load persistent data if exists (overriding defaults)
init_persistent_storage()

import asyncio
from datetime import timedelta, time, timezone

async def history_cleanup_task():
    while True:
        # Run every hour
        await asyncio.sleep(3600)
        
        now_utc = datetime.utcnow()
        twenty_four_hours_ago = now_utc - timedelta(hours=24)
        
        cleaned_count = 0
        for dev_id in list(device_history.keys()):
            raw_history = device_history.get(dev_id, [])
            filtered_history = []
            for point in raw_history:
                if len(point) >= 4:
                    try:
                        ts_str = point[3]
                        if ts_str.endswith('Z'):
                            dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                            dt_naive = dt.astimezone(timezone.utc).replace(tzinfo=None)
                        else:
                            dt = datetime.fromisoformat(ts_str)
                            dt_naive = dt.replace(tzinfo=None)
                        if dt_naive >= twenty_four_hours_ago:
                            filtered_history.append(point)
                    except Exception:
                        filtered_history.append(point)
                else:
                    filtered_history.append(point)
            
            device_history[dev_id] = filtered_history
            cleaned_count += len(raw_history) - len(filtered_history)
            
        if cleaned_count > 0:
            save_persistent_history()
            logger.info(f"Automatic rolling history cleanup: pruned {cleaned_count} points older than 24 hours across all devices.")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(history_cleanup_task())

@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    """
    Renders the main tracking map interface.
    """
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "devices": list(device_locations.keys()),
            "password_protected": False
        }
    )

@app.api_route("/api/tracking", methods=["GET", "POST"])
async def receive_tracking(
    request: Request,
    id: Optional[str] = Query(None),
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    timestamp: Optional[str] = Query(None),
    hdop: Optional[float] = Query(None),
    altitude: Optional[float] = Query(None),
    speed: Optional[float] = Query(None),
    battery: Optional[float] = Query(None),
    credentials: Optional[HTTPBasicCredentials] = Depends(security)
):
    """
    Endpoint for Traccar Client. Supports both GET and POST requests with query parameters.
    Also falls back to reading JSON body if query parameters are missing.
    """
    # 1. Parse parameters. Traccar Client sends values in query parameters by default.
    device_id = id
    latitude = lat
    longitude = lon
    
    # 2. If essential query parameters are missing, parse the request body (JSON or Form URL-encoded)
    if not device_id or latitude is None or longitude is None:
        try:
            content_type = request.headers.get("content-type", "")
            body_bytes = await request.body()
            body_str = body_bytes.decode("utf-8")
            
            body_data = {}
            if "application/json" in content_type:
                import json
                body_data = json.loads(body_str)
            elif body_str:
                # Parse as form urlencoded
                from urllib.parse import parse_qs
                body_data = {k: v[0] for k, v in parse_qs(body_str).items()}
                
            if isinstance(body_data, dict) and body_data:
                # Handle nested location wrapper (common in Background Geolocation plugins)
                location_data = body_data.get("location", body_data) if isinstance(body_data.get("location"), dict) else body_data
                
                # Check for dummy query string parameter "_" (often used as fallback in location templates)
                _field = location_data.get("_") if isinstance(location_data, dict) else None
                parsed_qs = {}
                if isinstance(_field, str) and _field:
                    from urllib.parse import parse_qs
                    parsed_qs = {k: v[0] for k, v in parse_qs(_field.lstrip("&").lstrip("?")).items()}

                # Parse Device ID (check root parameters, then nested, then custom query string)
                device_id = (
                    body_data.get("device_id") or 
                    body_data.get("id") or 
                    body_data.get("deviceid") or 
                    (body_data.get("params", {}).get("device_id") if isinstance(body_data.get("params"), dict) else None) or
                    (location_data.get("device_id") if isinstance(location_data, dict) else None) or
                    parsed_qs.get("id") or
                    parsed_qs.get("deviceid") or
                    parsed_qs.get("device_id") or
                    device_id
                )
                
                # Parse coords (could be nested inside a "coords" dictionary)
                if isinstance(location_data, dict):
                    coords = location_data.get("coords")
                    if isinstance(coords, dict) and coords:
                        latitude = coords.get("latitude") or coords.get("lat") or latitude
                        longitude = coords.get("longitude") or coords.get("lon") or longitude
                        altitude = coords.get("altitude") or altitude
                        hdop = coords.get("accuracy") or hdop
                        
                        # Speed in Background Geolocation is in m/s. Convert to knots.
                        speed_val = coords.get("speed")
                        if speed_val is not None:
                            try:
                                speed = float(speed_val) * 1.94384
                            except (ValueError, TypeError):
                                speed = speed_val
                    else:
                        latitude = location_data.get("lat") or location_data.get("latitude") or latitude
                        longitude = location_data.get("lon") or location_data.get("longitude") or longitude
                        altitude = location_data.get("altitude") or altitude
                        speed = location_data.get("speed") or speed
                        hdop = location_data.get("hdop") or hdop
                    
                    # Fallback coordinate and timestamp parsing from custom query string if missing
                    if latitude is None and parsed_qs.get("lat"):
                        try: latitude = float(parsed_qs.get("lat"))
                        except (ValueError, TypeError): pass
                    if longitude is None and parsed_qs.get("lon"):
                        try: longitude = float(parsed_qs.get("lon"))
                        except (ValueError, TypeError): pass
                    if not timestamp and parsed_qs.get("timestamp"):
                        timestamp = parsed_qs.get("timestamp")
                        
                    # Parse battery (could be nested or float)
                    battery_val = location_data.get("battery")
                    if isinstance(battery_val, dict):
                        battery = battery_val.get("level") or battery_val.get("percentage") or battery
                    elif battery_val is not None:
                        battery = battery_val
                        
                    # Scale battery from [0.0, 1.0] to [0.0, 100.0] if fraction
                    if battery is not None:
                        try:
                            batt_float = float(battery)
                            if 0.0 <= batt_float <= 1.0:
                                battery = batt_float * 100.0
                        except (ValueError, TypeError):
                            pass
                            
                    timestamp = location_data.get("timestamp") or timestamp
        except Exception as e:
            logger.error(f"Error parsing request body: {e}")

    # 3. Fallback check: check for "deviceid" instead of "id" query parameter
    if not device_id:
        device_id = request.query_params.get("deviceid")

    # 4. Validate required fields
    if not device_id:
        logger.warning("Tracking request rejected: Missing device 'id'.")
        raise HTTPException(status_code=400, detail="Missing parameter: 'id' or 'deviceid'")

    # Enforce basic authentication only if a password is set for this device
    required_password = DEVICE_PASSWORDS.get(str(device_id))
    
    if required_password:
        # Check query parameters first, then fallback to HTTP Basic credentials
        received_password = request.query_params.get("password") or request.query_params.get("pass") or request.query_params.get("secret")
        if not received_password and credentials:
            received_password = credentials.password
            
        if not received_password or received_password != required_password:
            logger.warning(
                f"Authentication required for device '{device_id}' rejected. "
                f"Required: '{required_password}', Received: '{received_password or 'None'}'"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to record location data.",
                headers={"WWW-Authenticate": "Basic"},
            )

    # Validate device authorization whitelist
    if ALLOWED_DEVICES and str(device_id) not in ALLOWED_DEVICES:
        logger.warning(f"Tracking request rejected: Device '{device_id}' is not authorized.")
        raise HTTPException(status_code=403, detail=f"Device '{device_id}' not authorized.")
    if latitude is None or longitude is None:
        logger.warning(f"Tracking request rejected for device '{device_id}': Missing latitude or longitude.")
        raise HTTPException(status_code=400, detail="Missing parameter: 'lat' and 'lon'")

    # 5. Process timestamp (Traccar sends epoch timestamp)
    parsed_time = None
    if timestamp:
        try:
            ts_val = float(timestamp)
            # Traccar Client may send timestamp in milliseconds or seconds.
            # If value represents a time beyond year 3000 in seconds, it is in milliseconds.
            if ts_val > 50000000000:
                ts_val = ts_val / 1000.0
            parsed_time = datetime.fromtimestamp(ts_val).isoformat()
        except Exception:
            parsed_time = str(timestamp)
    else:
        # Fallback to current server time if timestamp is missing
        parsed_time = datetime.utcnow().isoformat()

    # 6. Store update in-memory
    data = {
        "id": str(device_id),
        "lat": float(latitude),
        "lon": float(longitude),
        "timestamp": parsed_time,
        "hdop": float(hdop) if hdop is not None else None,
        "altitude": float(altitude) if altitude is not None else None,
        "speed": float(speed) if speed is not None else None,  # Speed in knots (Traccar Client default)
        "battery": float(battery) if battery is not None else None,
        "last_seen": datetime.utcnow().isoformat() + "Z"
    }
    
    device_locations[str(device_id)] = data
    
    # Append coordinate to history trail, including timestamp
    if str(device_id) not in device_history:
        device_history[str(device_id)] = []
    device_history[str(device_id)].append([
        float(latitude),
        float(longitude),
        float(altitude) if altitude is not None else 0.0,
        parsed_time
    ])
    # Limit size of history trail in memory to 2000 points
    if len(device_history[str(device_id)]) > 2000:
        device_history[str(device_id)].pop(0)
        
    save_persistent_locations()
    save_persistent_history()
    
    logger.info(f"Location updated for device '{device_id}': ({latitude}, {longitude}) - Batt: {battery}% - Speed: {speed} knots")
    
    # Traccar Client expects HTTP 200 OK with success response
    return {"status": "success", "message": "Location recorded successfully"}

@app.get("/api/location/{device_id}")
async def get_device_location(device_id: str):
    """
    Returns the latest location data and the historical trail for a specific device.
    """
    if device_id not in device_locations:
        return None
        
    # Filter history to last 24 hours
    now_utc = datetime.utcnow()
    twenty_four_hours_ago = now_utc - timedelta(hours=24)
    
    raw_history = device_history.get(str(device_id), [])
    filtered_history = []
    
    for point in raw_history:
        if len(point) >= 4:
            try:
                ts_str = point[3]
                if ts_str.endswith('Z'):
                    dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    dt_naive = dt.astimezone(timezone.utc).replace(tzinfo=None)
                else:
                    dt = datetime.fromisoformat(ts_str)
                    dt_naive = dt.replace(tzinfo=None)
                if dt_naive >= twenty_four_hours_ago:
                    filtered_history.append(point)
            except Exception:
                filtered_history.append(point)
        else:
            filtered_history.append(point)
            
    # Update stored history
    device_history[str(device_id)] = filtered_history
    
    # Return [lat, lon, alt] format to the frontend
    history_to_send = [[p[0], p[1], p[2]] for p in filtered_history]
    
    return {
        "latest": device_locations[device_id],
        "history": history_to_send
    }

@app.get("/api/devices")
async def list_devices():
    """
    Returns a list of all devices that have sent tracking data.
    """
    return list(device_locations.values())

@app.post("/api/location/{device_id}/clear")
async def clear_device_history(device_id: str, username: str = Depends(verify_credentials)):
    """
    Clears the historical path trail for a specific device.
    """
    if str(device_id) in device_history:
        device_history[str(device_id)] = []
        save_persistent_history()
    logger.info(f"History cleared for device '{device_id}' by user '{username}'")
    return {"status": "success", "message": f"History for device '{device_id}' has been cleared."}

@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.svg", include_in_schema=False)
async def get_favicon():
    return FileResponse("favicon.svg", media_type="image/svg+xml")
