"""Serving the built frontend, a single-page app, next to the API."""

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from hive.api.routes import API_PREFIX

FRONTEND_INDEX = "index.html"
"""The page of the single-page app, which handles every client-side route."""


class FrontendFiles(StaticFiles):
    """The files of the built frontend, falling back to its index page.

    Paths without a file, such as `/games/<id>`, are client-side routes, so they get the
    index page and the app routes them in the browser. Unknown paths under the API
    prefix stay 404, so API clients never receive the page.
    """

    def __init__(self, directory: str) -> None:
        """Serve the files of a built frontend.

        Args:
            directory: The build output, holding `index.html` and the assets.
        """
        super().__init__(directory=directory, html=True)

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Get the file at a path, or the index page for client-side routes.

        Args:
            path: The requested path relative to the mount, without a leading slash.
            scope: The ASGI scope of the request.

        Returns:
            The file, or the index page if there is none and the path is not under the
            API prefix.

        Raises:
            HTTPException: With status 404 if there is no file under the API prefix.
        """
        try:
            return await super().get_response(path, scope)
        except HTTPException as e:
            api_root = API_PREFIX.removeprefix("/")

            if (
                e.status_code != 404
                or path == api_root
                or path.startswith(f"{api_root}/")
            ):
                raise

            return await super().get_response(FRONTEND_INDEX, scope)
