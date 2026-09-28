from rest_framework.views import exception_handler
from rest_framework.response import Response

def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        custom_data = {
            "error": {
                "code": exc.__class__.__name__,
                "message": str(exc),
                "details": response.data
            }
        }
        response.data = custom_data
    return response
