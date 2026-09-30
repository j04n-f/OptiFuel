from fastapi import Request

from optifuel.config import Settings


# Providers read what api.create_app put on app.state; tests swap them via dependency_overrides.
def get_settings(request: Request) -> Settings:
    return request.app.state.settings
