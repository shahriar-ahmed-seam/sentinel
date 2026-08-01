"""HTTP surface, split by bounded context."""

from . import analytics, auth, catalog, inference, ops, system, traffic

ROUTERS = (
    system.router,
    auth.router,
    inference.router,
    catalog.router,
    traffic.router,
    analytics.router,
    ops.router,
)

__all__ = ["ROUTERS"]
