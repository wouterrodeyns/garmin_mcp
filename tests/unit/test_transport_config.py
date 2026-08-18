"""Unit tests for HTTP transport configuration (_parse_transport_config)."""

import os
import pytest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecurityMiddleware
from starlette.requests import Request

from garmin_mcp import _parse_transport_config, _VALID_TRANSPORTS


class TestParseTransportConfig:
    """Tests for _parse_transport_config."""

    def test_default_is_stdio(self):
        with patch.dict(os.environ, {}, clear=True):
            transport, host, port = _parse_transport_config()
        assert transport == "stdio"
        assert host == "127.0.0.1"
        assert port == 8000

    @pytest.mark.parametrize("value", list(_VALID_TRANSPORTS))
    def test_valid_transports_are_accepted(self, value):
        with patch.dict(
            os.environ,
            {
                "GARMIN_MCP_TRANSPORT": value,
                "GARMIN_MCP_HOST": "127.0.0.1",
                "GARMIN_MCP_PORT": "8000",
            },
            clear=True,
        ):
            transport, _, _ = _parse_transport_config()
        assert transport == value

    def test_transport_value_is_lowercased(self):
        with patch.dict(
            os.environ,
            {
                "GARMIN_MCP_TRANSPORT": "STDIO",
                "GARMIN_MCP_HOST": "127.0.0.1",
                "GARMIN_MCP_PORT": "8000",
            },
            clear=True,
        ):
            transport, _, _ = _parse_transport_config()
        assert transport == "stdio"

    def test_transport_value_is_stripped(self):
        with patch.dict(
            os.environ,
            {
                "GARMIN_MCP_TRANSPORT": "  streamable-http  ",
                "GARMIN_MCP_HOST": "127.0.0.1",
                "GARMIN_MCP_PORT": "8000",
            },
            clear=True,
        ):
            transport, _, _ = _parse_transport_config()
        assert transport == "streamable-http"

    def test_invalid_transport_raises_value_error(self):
        with patch.dict(
            os.environ,
            {"GARMIN_MCP_TRANSPORT": "TOP_SECRET_TRANSPORT"},
            clear=True,
        ):
            with pytest.raises(ValueError) as error:
                _parse_transport_config()

        assert str(error.value) == (
            "Invalid GARMIN_MCP_TRANSPORT; expected one of "
            "stdio, streamable-http, sse"
        )
        assert "TOP_SECRET_TRANSPORT" not in str(error.value)

    def test_custom_host_is_read(self):
        with patch.dict(
            os.environ,
            {
                "GARMIN_MCP_TRANSPORT": "stdio",
                "GARMIN_MCP_HOST": "127.0.0.1",
                "GARMIN_MCP_PORT": "8000",
            },
            clear=True,
        ):
            _, host, _ = _parse_transport_config()
        assert host == "127.0.0.1"

    def test_custom_port_is_read(self):
        with patch.dict(
            os.environ,
            {
                "GARMIN_MCP_TRANSPORT": "stdio",
                "GARMIN_MCP_HOST": "127.0.0.1",
                "GARMIN_MCP_PORT": "9000",
            },
            clear=True,
        ):
            _, _, port = _parse_transport_config()
        assert port == 9000

    @pytest.mark.parametrize("value", ("TOP_SECRET_PORT", "-1", "0", "65536", "70000"))
    def test_invalid_port_raises_fixed_value_free_error(self, value):
        with patch.dict(
            os.environ,
            {
                "GARMIN_MCP_TRANSPORT": "stdio",
                "GARMIN_MCP_HOST": "127.0.0.1",
                "GARMIN_MCP_PORT": value,
            },
            clear=True,
        ):
            with pytest.raises(ValueError) as error:
                _parse_transport_config()

        assert str(error.value) == (
            "GARMIN_MCP_PORT must be an integer from 1 through 65535"
        )
        assert "TOP_SECRET_PORT" not in str(error.value)

    @pytest.mark.parametrize("value", ("1", "65535"))
    def test_port_range_boundaries_are_accepted(self, value):
        with patch.dict(
            os.environ,
            {
                "GARMIN_MCP_TRANSPORT": "stdio",
                "GARMIN_MCP_HOST": "127.0.0.1",
                "GARMIN_MCP_PORT": value,
            },
            clear=True,
        ):
            assert _parse_transport_config()[2] == int(value)

    @pytest.mark.parametrize("transport", ("streamable-http", "sse"))
    @pytest.mark.parametrize(
        ("host", "expected_host"),
        (
            ("localhost", "127.0.0.1"),
            ("LOCALHOST.", "127.0.0.1"),
            ("127.0.0.1", "127.0.0.1"),
            ("127.0.0.42", "127.0.0.1"),
            ("::1", "::1"),
        ),
    )
    def test_http_transports_canonicalize_loopback_hosts(
        self, transport, host, expected_host
    ):
        with patch.dict(
            os.environ,
            {
                "GARMIN_MCP_TRANSPORT": transport,
                "GARMIN_MCP_HOST": host,
                "GARMIN_MCP_PORT": "8000",
            },
            clear=True,
        ):
            assert _parse_transport_config() == (transport, expected_host, 8000)

    @pytest.mark.parametrize("transport", ("streamable-http", "sse"))
    @pytest.mark.parametrize("configured_host", ("127.0.0.1", "127.0.0.42", "::1"))
    @pytest.mark.asyncio
    async def test_every_accepted_loopback_rejects_host_header_rebinding(
        self, transport, configured_host
    ):
        with patch.dict(
            os.environ,
            {
                "GARMIN_MCP_TRANSPORT": transport,
                "GARMIN_MCP_HOST": configured_host,
                "GARMIN_MCP_PORT": "8000",
            },
            clear=True,
        ):
            _, parsed_host, _ = _parse_transport_config()

        server = FastMCP("transport-security-probe", host=parsed_host)
        middleware = TransportSecurityMiddleware(server.settings.transport_security)
        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/mcp" if transport == "streamable-http" else "/sse",
                "raw_path": b"/mcp" if transport == "streamable-http" else b"/sse",
                "query_string": b"",
                "headers": (
                    (b"content-type", b"application/json"),
                    (b"host", b"attacker.invalid"),
                    (b"origin", b"http://attacker.invalid"),
                ),
                "client": ("127.0.0.1", 12345),
                "server": (parsed_host, 8000),
            }
        )
        response = await middleware.validate_request(request, is_post=True)

        assert response is not None
        assert response.status_code == 421
        assert bytes(response.body) == b"Invalid Host header"

    @pytest.mark.parametrize("transport", ("streamable-http", "sse"))
    @pytest.mark.parametrize(
        "host",
        ("", "   ", "0.0.0.0", "::", "192.168.1.2", "8.8.8.8", "example.com"),
    )
    def test_http_transports_reject_nonloopback_hosts_by_default(self, transport, host):
        with patch.dict(
            os.environ,
            {
                "GARMIN_MCP_TRANSPORT": transport,
                "GARMIN_MCP_HOST": host,
                "GARMIN_MCP_PORT": "8000",
            },
            clear=True,
        ):
            with pytest.raises(ValueError) as error:
                _parse_transport_config()

        assert str(error.value) == (
            "Refusing unauthenticated remote HTTP binding because this server does "
            "not provide HTTP authentication. Use an authenticating reverse proxy, "
            "or explicitly set GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE=true to "
            "accept this danger."
        )

    @pytest.mark.parametrize("transport", ("streamable-http", "sse"))
    @pytest.mark.parametrize("override", ("true", " TRUE ", "1", "yes", "YeS"))
    def test_true_override_allows_remote_http_hosts(self, transport, override):
        with patch.dict(
            os.environ,
            {
                "GARMIN_MCP_TRANSPORT": transport,
                "GARMIN_MCP_HOST": " 192.168.1.2 ",
                "GARMIN_MCP_PORT": "8000",
                "GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE": override,
            },
            clear=True,
        ):
            assert _parse_transport_config() == (transport, "192.168.1.2", 8000)

    @pytest.mark.parametrize("override", (None, "false", "0", "no", "off", "maybe"))
    def test_missing_false_or_garbage_override_rejects_remote_http_host(self, override):
        environment = {
            "GARMIN_MCP_TRANSPORT": "streamable-http",
            "GARMIN_MCP_HOST": "192.168.1.2",
            "GARMIN_MCP_PORT": "8000",
        }
        if override is not None:
            environment["GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE"] = override

        with patch.dict(os.environ, environment, clear=True):
            with pytest.raises(ValueError):
                _parse_transport_config()

    @pytest.mark.parametrize("override", (None, "false", "true", "garbage"))
    def test_stdio_ignores_nonloopback_host_regardless_of_override(self, override):
        environment = {
            "GARMIN_MCP_TRANSPORT": "stdio",
            "GARMIN_MCP_HOST": " 0.0.0.0 ",
            "GARMIN_MCP_PORT": "8000",
        }
        if override is not None:
            environment["GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE"] = override

        with patch.dict(os.environ, environment, clear=True):
            assert _parse_transport_config() == ("stdio", "0.0.0.0", 8000)
