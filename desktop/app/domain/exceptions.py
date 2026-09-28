class PharmacyError(Exception):
    pass

class AuthenticationError(PharmacyError):
    pass

class PermissionDeniedError(PharmacyError):
    pass

class ValidationError(PharmacyError):
    pass

class InsufficientStockError(PharmacyError):
    pass

class SyncError(PharmacyError):
    pass

class NetworkError(PharmacyError):
    pass

class OfflineError(PharmacyError):
    pass

