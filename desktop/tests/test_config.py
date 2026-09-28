def test_app_config(app_config):
    assert app_config.server_url == "http://testserver"
    assert app_config.data_dir.exists()
    assert app_config.db_path.name == "pharmacy.db"

