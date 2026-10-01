class MaintenanceError(ValueError):
    """Base class for errors safe to show in Office Hub or Slack."""


class InvalidTransitionError(MaintenanceError):
    pass


class InvalidPhoneError(MaintenanceError):
    pass


class InvalidMediaError(MaintenanceError):
    pass


class PermissionDeniedError(MaintenanceError):
    pass


class EntryNoticeError(MaintenanceError):
    pass
