class DuplicateError(Exception):
    """Raised when a unique constraint would be violated."""

    def __init__(self, detail: str = "Resource already exists"):
        self.detail = detail
        super().__init__(detail)
