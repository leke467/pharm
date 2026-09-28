import httpx
import pytest
from desktop.app.domain.exceptions import NetworkError, AuthenticationError, PharmacyError


def test_api_client(api_client):
    api_client.set_auth_token("token")
    assert api_client.access_token == "token"
    assert not api_client.is_server_available()  # no testserver running


def test_api_client_error_parsing_sanitizes_html(api_client):
    # Simulate Django 404 HTML debug page
    req = httpx.Request("POST", "http://localhost:8000/api/v1/auth/login/")
    html_resp = httpx.Response(
        404,
        request=req,
        text="<!DOCTYPE html><html><head><title>Page not found</title></head><body><h1>404</h1></body></html>",
    )
    clean_msg = api_client._parse_error_message(html_resp)
    assert "<!DOCTYPE" not in clean_msg
    assert "<html>" not in clean_msg
    assert "404" in clean_msg


def test_api_client_error_parsing_extracts_json_messages(api_client):
    req = httpx.Request("POST", "http://localhost:8000/api/v1/auth/login/")
    # Format 1: DRF detail
    json_resp1 = httpx.Response(400, request=req, json={"detail": "Invalid credentials provided."})
    assert api_client._parse_error_message(json_resp1) == "Invalid credentials provided."

    # Format 2: Field error
    json_resp2 = httpx.Response(400, request=req, json={"username": ["This field may not be blank."]})
    assert api_client._parse_error_message(json_resp2) == "Username: This field may not be blank."

    # Format 3: Custom error dict
    json_resp3 = httpx.Response(400, request=req, json={"error": {"message": "Account suspended."}})
    assert api_client._parse_error_message(json_resp3) == "Account suspended."
