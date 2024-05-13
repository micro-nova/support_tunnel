import logging

from fastapi import FastAPI, APIRouter

from api.device import device
from api.admin import admin

logging.basicConfig(level=logging.INFO)

app = FastAPI()
api = APIRouter(prefix="/v1")  # provides simple versioning

# Import all api functions and serve them.
api.include_router(device)
api.include_router(admin)

app.include_router(api)
