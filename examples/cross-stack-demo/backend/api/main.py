"""FastAPI app for the cross-stack demo."""
from fastapi import FastAPI

from backend.api.routes import orders, users

app = FastAPI(title="cross-stack-demo")
app.include_router(users.router)
app.include_router(orders.router)
