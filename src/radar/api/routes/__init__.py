"""Resource routers for API version 1."""

from radar.api.routes.capacity import router as capacity_router
from radar.api.routes.catalog import router as catalog_router
from radar.api.routes.deployments import router as deployments_router
from radar.api.routes.integrations import router as integrations_router
from radar.api.routes.operations import router as operations_router
from radar.api.routes.releases import router as releases_router
from radar.api.routes.workspaces import router as workspaces_router


ROUTERS = (
    releases_router,
    catalog_router,
    capacity_router,
    deployments_router,
    workspaces_router,
    operations_router,
    integrations_router,
)


__all__ = ["ROUTERS"]
