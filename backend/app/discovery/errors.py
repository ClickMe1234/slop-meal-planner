class DiscoveryError(RuntimeError):
    """Base class for user-safe recipe discovery failures."""

    code = "DISCOVERY_ERROR"


class InvalidUrlError(DiscoveryError):
    code = "INVALID_URL"


class UnsafeUrlError(DiscoveryError):
    code = "UNSAFE_URL"


class UnsupportedSourceError(DiscoveryError):
    code = "UNSUPPORTED_SOURCE"


class FetchError(DiscoveryError):
    code = "FETCH_FAILED"


class ResponseTooLargeError(FetchError):
    code = "RESPONSE_TOO_LARGE"
