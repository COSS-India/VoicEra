"""Campaign-specific exceptions."""


class ConcurrentSlotAcquisitionError(Exception):
    """Raised when a concurrent call slot cannot be acquired in time."""

    def __init__(self, message: str = "Concurrent slot acquisition timeout") -> None:
        super().__init__(message)


class PhoneNumberPoolExhaustedError(Exception):
    """Raised when no from_number is available in the pool."""

    def __init__(self, *, organization_id: str) -> None:
        self.organization_id = organization_id
        super().__init__(
            f"Phone number pool exhausted for org {organization_id}"
        )
