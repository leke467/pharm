from desktop.app.auth.offline_auth import OfflineAuthenticator

def test_offline_auth():
    auth = OfflineAuthenticator()
    pwd = "MySecretPassword123"
    hashed = auth.create_offline_hash(pwd)
    
    assert hashed.startswith("$2")
    assert auth.verify_password(pwd, hashed)
    assert not auth.verify_password("wrong", hashed)

