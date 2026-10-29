import httpx
from databricks.sdk.core import Config


class DatabricksOAuth(httpx.Auth):
    """Attach a refreshable Databricks OAuth token to every A2A request.

    A local demo supplies a named CLI profile. A Google Cloud deployment omits
    the profile and lets Config discover DATABRICKS_HOST,
    DATABRICKS_CLIENT_ID, and DATABRICKS_CLIENT_SECRET.
    """

    def __init__(self, profile: str | None = None):
        self._config = Config(profile=profile) if profile else Config()

    def auth_flow(self, request):
        token = self._config.oauth_token().access_token
        request.headers["Authorization"] = f"Bearer {token}"
        yield request
