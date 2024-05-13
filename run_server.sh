#!/bin/sh

python3 -m uvicorn --reload --reload-exclude web --host 0.0.0.0 api.app:app 
