import uuid

def generate_uuid() -> str:
    return str(uuid.uuid4())

def is_valid_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False

