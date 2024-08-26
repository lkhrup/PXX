from typing import Mapping

from flask import request
from unpoly.adapter import BaseAdapter


class FlaskAdapter(BaseAdapter):
    def __init__(self):
        self._request = request

    def request_headers(self) -> Mapping[str, str]:
        """Reads the request headers from the current request."""
        return dict(self._request.headers)

    def request_params(self) -> Mapping[str, str]:
        """Reads the GET params from the current request."""
        return self._request.args.to_dict()

    def redirect_uri(self, response) -> str | None:
        """Returns the redirect target of a response, or None if not a redirection."""
        if 300 <= response.status_code < 400:
            return response.headers.get('Location')
        return None

    def set_redirect_uri(self, response, uri: str) -> None:
        """Set a new redirect target for the current response."""
        response.headers['Location'] = uri

    def set_headers(self, response, headers: Mapping[str, str]) -> None:
        """Set headers like `X-Up-Location` on the current response."""
        for key, value in headers.items():
            response.headers[key] = value

    def set_cookie(self, response, needs_cookie: bool = False) -> None:
        """Set or delete the `_up_method` cookie."""
        if needs_cookie:
            response.set_cookie('_up_method', self._request.method)
        else:
            response.delete_cookie('_up_method')

    @property
    def method(self) -> str:
        """Exposes the current request's method (GET/POST etc)."""
        return self._request.method

    @property
    def location(self) -> str:
        """Exposes the current request's location (path including query params)."""
        return self._request.path + '?' + self._request.query_string.decode('utf-8')
