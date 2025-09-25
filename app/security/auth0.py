from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from jose import JWTError, jwt

from app.core.config import Settings


class Auth0TokenVerifier:
    """Validate Auth0-issued JWT access tokens."""

    class TokenVerificationError(Exception):
        """Raised when verification fails."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jwks_cache: JWKSCache | None = None

    def verify(self, token: str) -> dict:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        if not algorithm or algorithm not in self._settings.auth0_algorithms:
            raise self.TokenVerificationError("Unsupported signing algorithm")

        issuer = f"https://{self._settings.auth0_domain}/"

        try:
            if algorithm.startswith("HS"):
                return jwt.decode(
                    token,
                    self._settings.auth0_client_secret,
                    algorithms=[algorithm],
                    audience=self._settings.auth0_audience,
                    issuer=issuer,
                )

            kid = header.get("kid")
            if not kid:
                raise self.TokenVerificationError("Missing key id for asymmetric token")

            jwks_cache = self._get_jwks_cache()
            rsa_key = jwks_cache.get_key(kid)
            return jwt.decode(
                token,
                rsa_key,
                algorithms=[algorithm],
                audience=self._settings.auth0_audience,
                issuer=issuer,
            )
        except (JWTError, httpx.HTTPError) as exc:
            raise self.TokenVerificationError("JWT validation failure") from exc

    def _get_jwks_cache(self) -> "JWKSCache":
        if self._jwks_cache is None:
            self._jwks_cache = JWKSCache(self._settings)
        return self._jwks_cache


@dataclass(slots=True)
class JWKSCache:
    settings: Settings
    _jwks: dict | None = None
    _fetched_at: float = 0.0

    def get_key(self, kid: str) -> dict:
        jwks = self._get_jwks()
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key.get("use", "sig"),
                    "n": key["n"],
                    "e": key["e"],
                }
        raise Auth0TokenVerifier.TokenVerificationError("Signing key not found")

    def _get_jwks(self) -> dict:
        now = time.monotonic()
        if self._jwks and now - self._fetched_at < self.settings.auth0_jwks_cache_ttl:
            return self._jwks

        url = f"https://{self.settings.auth0_domain}/.well-known/jwks.json"
        try:
            response = httpx.get(url, timeout=5.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:  # pragma: no cover - network failure is unlikely in tests
            raise Auth0TokenVerifier.TokenVerificationError("Unable to fetch JWKS") from exc

        self._jwks = response.json()
        self._fetched_at = now
        return self._jwks
