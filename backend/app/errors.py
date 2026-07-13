class DomainError(Exception):
    def __init__(
        self,
        code: str,
        detail: str,
        status_code: int = 422,
        *,
        actions: list[dict] | None = None,
        issues: list[dict] | None = None,
    ):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code
        self.actions = actions or []
        self.issues = issues or []


class ConflictError(DomainError):
    def __init__(self, detail: str = "The record was changed by another user"):
        super().__init__("VERSION_CONFLICT", detail, 409)


class NotFoundError(DomainError):
    def __init__(self, resource: str):
        super().__init__("NOT_FOUND", f"{resource} was not found", 404)

