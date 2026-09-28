import bcrypt

class OfflineAuthenticator:
    def verify_password(self, entered_password: str, stored_hash: str) -> bool:
        if not entered_password or not stored_hash:
            return False
        try:
            return bcrypt.checkpw(entered_password.encode('utf-8'), stored_hash.encode('utf-8'))
        except ValueError:
            return False

    def create_offline_hash(self, plaintext_password: str) -> str:
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(plaintext_password.encode('utf-8'), salt)
        return hashed.decode('utf-8')

