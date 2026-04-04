from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from logging import Logger
from typing import Any, Dict, Literal, Optional
from urllib.request import Request, urlopen

try:
    from netmiko import ConnectHandler
    NETMIKO_IMPORT_ERROR: BaseException | None = None
except ImportError as exc:  # pragma: no cover
    ConnectHandler = None
    NETMIKO_IMPORT_ERROR = exc

from .constants import CONNECT_CHECK_COMMAND_MAP, DEFAULT_CONNECT_CHECK_TIMEOUT, PRIVILEGED_EXEC_DEVICE_TYPES
from .utils import get_netmiko_unavailable_message, get_ssh_options

TransportType = Literal["auto", "nxapi", "ssh"]


@dataclass
class CommandResult:
    """
    Normalized command execution result across SSH and NX-API.
    """

    command: str
    ok: bool
    output: str
    transport: str
    error: Optional[str] = None
    fallback_from: Optional[str] = None
    output_format: Optional[str] = None


@dataclass
class ConnectCheckResult:
    """
    Normalized pre-flight connectivity/authentication check result.
    """

    hostname: str
    ip: str
    requested_transport: str
    resolved_transport: Optional[str]
    ok: bool
    stage: str
    elapsed_seconds: float
    error: Optional[str] = None
    fallback_from: Optional[str] = None


class BaseCollector(ABC):
    """
    Abstract command collector.
    """

    def __init__(
        self,
        host: Dict[str, Any],
        username: str,
        password: str,
        enable_secret: str,
        logger: Logger,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.enable_secret = enable_secret
        self.logger = logger

    @property
    def hostname(self) -> str:
        return str(self.host["hostname"])

    @property
    def ip(self) -> str:
        return str(self.host["ip"])

    @property
    def device_type(self) -> str:
        return str(self.host.get("device_type") or self.host.get("os_type") or "unknown")

    def log_command_failure(self, result: CommandResult) -> None:
        """
        Log command-level failure without aborting whole host processing.
        """
        fallback = f" fallback_from={result.fallback_from}" if result.fallback_from else ""
        self.logger.warning(
            "COMMAND FAILED %s transport=%s%s command=%s error=%s",
            self.hostname,
            result.transport,
            fallback,
            result.command,
            result.error or "unknown error",
        )

    @abstractmethod
    def run_command(self, command: str, read_timeout: int) -> CommandResult:
        """
        Execute one command and return a normalized result.
        """

    def close(self) -> None:
        """
        Close transport if needed.
        """


class SshCollector(BaseCollector):
    """
    SSH/Netmiko-backed collector.
    """

    def __init__(
        self,
        host: Dict[str, Any],
        username: str,
        password: str,
        enable_secret: str,
        logger: Logger,
    ) -> None:
        super().__init__(host, username, password, enable_secret, logger)
        self._conn: Any = None

    def _connect(self) -> Any:
        if self._conn is not None:
            return self._conn
        if ConnectHandler is None:
            raise RuntimeError(get_netmiko_unavailable_message(NETMIKO_IMPORT_ERROR))

        netmiko_device_type = self.host.get("netmiko_device_type")
        if not netmiko_device_type:
            raise ValueError(
                f"{self.hostname}: netmiko_device_type is not defined for device_type={self.device_type}"
            )

        conn_params = {
            "device_type": netmiko_device_type,
            "host": self.ip,
            "username": self.username,
            "password": self.password,
            **get_ssh_options(),
        }
        if self.enable_secret:
            conn_params["secret"] = self.enable_secret

        self.logger.info("CONNECT %s (%s %s) transport=ssh", self.hostname, self.device_type, self.ip)
        self._conn = ConnectHandler(**conn_params)

        if self.device_type in PRIVILEGED_EXEC_DEVICE_TYPES:
            if not self.enable_secret:
                self._conn.disconnect()
                self._conn = None
                raise ValueError(
                    f"{self.hostname}: device_type={self.device_type} requires enable secret. "
                    "Use --enable-secret or define ALRED_ENABLE_SECRET."
                )
            self.logger.info("ENABLE %s transport=ssh", self.hostname)
            self._conn.enable()

        return self._conn

    def run_command(self, command: str, read_timeout: int) -> CommandResult:
        self.logger.info("RUN %s transport=ssh: %s", self.hostname, command)
        try:
            output = self._connect().send_command(command, read_timeout=read_timeout)
            return CommandResult(
                command=command,
                ok=True,
                output=output,
                transport="ssh",
            )
        except Exception as exc:
            result = CommandResult(
                command=command,
                ok=False,
                output=str(exc),
                transport="ssh",
                error=str(exc),
            )
            self.log_command_failure(result)
            return result

    def close(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.disconnect()
        finally:
            self.logger.info("DISCONNECT %s transport=ssh", self.hostname)
            self._conn = None


class NxapiCollector(BaseCollector):
    """
    NX-API-backed collector for NX-OS devices.
    """

    def __init__(
        self,
        host: Dict[str, Any],
        username: str,
        password: str,
        enable_secret: str,
        logger: Logger,
    ) -> None:
        super().__init__(host, username, password, enable_secret, logger)
        verify_ssl = os.environ.get("ALRED_NXAPI_VERIFY_SSL", os.environ.get("NW_TOOL_NXAPI_VERIFY_SSL", "0")).lower() in {"1", "true", "yes", "on"}
        self._ssl_context = ssl.create_default_context() if verify_ssl else ssl._create_unverified_context()
        self._schemes = self._resolve_schemes()
        self._timeout_default = int(
            os.environ.get(
                "ALRED_NXAPI_TIMEOUT",
                os.environ.get("NW_TOOL_NXAPI_TIMEOUT", os.environ.get("ALRED_TIMEOUT", os.environ.get("NW_TOOL_TIMEOUT", "60"))),
            )
        )

    def _resolve_schemes(self) -> list[str]:
        configured = os.environ.get("ALRED_NXAPI_SCHEME", os.environ.get("NW_TOOL_NXAPI_SCHEME", "")).strip().lower()
        if configured in {"https", "http"}:
            return [configured]
        return ["https", "http"]

    def _build_url(self, scheme: str) -> str:
        port_env = os.environ.get("ALRED_NXAPI_PORT", os.environ.get("NW_TOOL_NXAPI_PORT", "")).strip()
        default_port = "443" if scheme == "https" else "80"
        port = port_env or default_port
        return f"{scheme}://{self.ip}:{port}/ins"

    def _send_request(self, command: str, output_format: str, read_timeout: int) -> Dict[str, Any]:
        payload = {
            "ins_api": {
                "version": "1.0",
                "type": "cli_show",
                "chunk": "0",
                "sid": "1",
                "input": command,
                "output_format": output_format,
            }
        }
        body = json.dumps(payload).encode("utf-8")
        auth = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("ascii")
        timeout = max(read_timeout, self._timeout_default)
        last_error: Optional[Exception] = None

        for scheme in self._schemes:
            url = self._build_url(scheme)
            request = Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Basic {auth}",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=timeout, context=self._ssl_context) as response:
                    response_text = response.read().decode("utf-8", errors="replace")
                self.logger.info(
                    "RUN %s transport=nxapi scheme=%s format=%s: %s",
                    self.hostname,
                    scheme,
                    output_format,
                    command,
                )
                return json.loads(response_text)
            except Exception as exc:
                last_error = exc
                self.logger.warning(
                    "NXAPI REQUEST FAILED %s scheme=%s format=%s command=%s error=%s",
                    self.hostname,
                    scheme,
                    output_format,
                    command,
                    exc,
                )

        if last_error is None:
            raise RuntimeError("NX-API request failed without an explicit error")
        raise RuntimeError(str(last_error))

    def _extract_json_output(self, response: Dict[str, Any]) -> Optional[str]:
        ins_api = response.get("ins_api")
        if not isinstance(ins_api, dict):
            raise RuntimeError("NX-API response missing ins_api object")

        outputs = ins_api.get("outputs", {})
        output = outputs.get("output") if isinstance(outputs, dict) else None
        if isinstance(output, list):
            output = output[0] if output else None
        if not isinstance(output, dict):
            raise RuntimeError("NX-API response missing output object")

        code = str(output.get("code", ""))
        if code and code != "200":
            raise RuntimeError(str(output.get("msg") or output.get("clierror") or f"NX-API code={code}"))

        body = output.get("body")
        if isinstance(body, str):
            return body
        if isinstance(body, (dict, list)):
            return json.dumps(body, ensure_ascii=False, indent=2)
        return None

    def _extract_text_output(self, response: Dict[str, Any]) -> str:
        ins_api = response.get("ins_api")
        if not isinstance(ins_api, dict):
            raise RuntimeError("NX-API response missing ins_api object")

        outputs = ins_api.get("outputs", {})
        output = outputs.get("output") if isinstance(outputs, dict) else None
        if isinstance(output, list):
            output = output[0] if output else None
        if not isinstance(output, dict):
            raise RuntimeError("NX-API response missing output object")

        code = str(output.get("code", ""))
        if code and code != "200":
            raise RuntimeError(str(output.get("msg") or output.get("clierror") or f"NX-API code={code}"))

        body = output.get("body")
        if isinstance(body, str):
            return body
        if isinstance(body, (dict, list)):
            # Some NX-API responses still place structured data in body even when text was requested.
            return json.dumps(body, ensure_ascii=False, indent=2)

        msg = output.get("msg")
        if isinstance(msg, str):
            return msg

        raise RuntimeError("NX-API text response does not contain a string body")

    def run_command(self, command: str, read_timeout: int) -> CommandResult:
        json_error: Optional[str] = None
        try:
            response = self._send_request(command, output_format="json", read_timeout=read_timeout)
            output = self._extract_json_output(response)
            if output is not None:
                return CommandResult(
                    command=command,
                    ok=True,
                    output=output,
                    transport="nxapi",
                    output_format="json",
                )
            json_error = "JSON body is structured; falling back to text output"
            self.logger.info("NXAPI FORMAT FALLBACK %s command=%s reason=%s", self.hostname, command, json_error)
        except Exception as exc:
            json_error = str(exc)
            self.logger.warning(
                "NXAPI JSON FAILED %s command=%s error=%s",
                self.hostname,
                command,
                json_error,
            )

        try:
            response = self._send_request(command, output_format="text", read_timeout=read_timeout)
            output = self._extract_text_output(response)
            return CommandResult(
                command=command,
                ok=True,
                output=output,
                transport="nxapi",
                output_format="text",
                error=json_error,
            )
        except Exception as exc:
            result = CommandResult(
                command=command,
                ok=False,
                output=str(exc),
                transport="nxapi",
                error=str(exc),
                output_format="text",
            )
            self.log_command_failure(result)
            return result


class AutoCollector(BaseCollector):
    """
    Prefer NX-API on NX-OS and fall back to SSH when needed.
    """

    def __init__(
        self,
        host: Dict[str, Any],
        username: str,
        password: str,
        enable_secret: str,
        logger: Logger,
    ) -> None:
        super().__init__(host, username, password, enable_secret, logger)
        self._nxapi = NxapiCollector(host, username, password, enable_secret, logger)
        self._ssh = SshCollector(host, username, password, enable_secret, logger)

    def run_command(self, command: str, read_timeout: int) -> CommandResult:
        nxapi_result = self._nxapi.run_command(command, read_timeout=read_timeout)
        if nxapi_result.ok:
            return nxapi_result

        self.logger.warning(
            "TRANSPORT FALLBACK %s command=%s from=nxapi to=ssh error=%s",
            self.hostname,
            command,
            nxapi_result.error or "unknown error",
        )
        ssh_result = self._ssh.run_command(command, read_timeout=read_timeout)
        if ssh_result.ok:
            ssh_result.fallback_from = "nxapi"
        elif not ssh_result.error:
            ssh_result.error = nxapi_result.error
        return ssh_result

    def close(self) -> None:
        self._ssh.close()


def is_nxos_host(host: Dict[str, Any]) -> bool:
    """
    Return True when host is treated as NX-OS.
    """
    os_type = str(host.get("os_type") or "").strip().lower()
    device_type = str(host.get("device_type") or "").strip().lower()
    return os_type == "nxos" or device_type == "nxos"


def build_collector(
    host: Dict[str, Any],
    username: str,
    password: str,
    enable_secret: str,
    logger: Logger,
    transport: TransportType,
) -> BaseCollector:
    """
    Build the appropriate collector for the host and requested transport.
    """
    if transport == "ssh":
        return SshCollector(host, username, password, enable_secret, logger)

    if transport == "nxapi":
        if is_nxos_host(host):
            return NxapiCollector(host, username, password, enable_secret, logger)
        logger.info(
            "TRANSPORT OVERRIDE %s: device_type=%s does not support NX-API collector, using ssh",
            host["hostname"],
            host.get("device_type") or host.get("os_type") or "unknown",
        )
        return SshCollector(host, username, password, enable_secret, logger)

    if is_nxos_host(host):
        return AutoCollector(host, username, password, enable_secret, logger)

    return SshCollector(host, username, password, enable_secret, logger)


def _tcp_probe(ip: str, port: int, timeout: float) -> None:
    """
    Open and immediately close a TCP connection.
    """
    with socket.create_connection((ip, port), timeout=timeout):
        return


def _get_connect_check_command(device_type: str) -> str:
    """
    Return lightweight command used for authentication check.
    """
    cmd = CONNECT_CHECK_COMMAND_MAP.get(device_type)
    if cmd:
        return cmd
    return "show clock"


def probe_ssh_connectivity(
    host: Dict[str, Any],
    username: str,
    password: str,
    enable_secret: str,
    logger: Logger,
    timeout: float = DEFAULT_CONNECT_CHECK_TIMEOUT,
) -> ConnectCheckResult:
    """
    Validate SSH reachability plus login/enable readiness.
    """
    hostname = str(host["hostname"])
    ip = str(host["ip"])
    ssh_port = int(get_ssh_options().get("port", 22))
    started_at = time.perf_counter()
    try:
        _tcp_probe(ip, ssh_port, timeout)
    except Exception as exc:
        return ConnectCheckResult(
            hostname=hostname,
            ip=ip,
            requested_transport="ssh",
            resolved_transport=None,
            ok=False,
            stage="tcp",
            elapsed_seconds=time.perf_counter() - started_at,
            error=f"ssh tcp connect failed on port {ssh_port}: {exc}",
        )

    collector = SshCollector(host, username, password, enable_secret, logger)
    try:
        collector._connect()
        stage = "enable" if collector.device_type in PRIVILEGED_EXEC_DEVICE_TYPES else "auth"
        return ConnectCheckResult(
            hostname=hostname,
            ip=ip,
            requested_transport="ssh",
            resolved_transport="ssh",
            ok=True,
            stage=stage,
            elapsed_seconds=time.perf_counter() - started_at,
        )
    except Exception as exc:
        error_text = str(exc)
        stage = "auth"
        if collector.device_type in PRIVILEGED_EXEC_DEVICE_TYPES and (
            "enable" in error_text.lower() or "secret" in error_text.lower()
        ):
            stage = "enable"
        return ConnectCheckResult(
            hostname=hostname,
            ip=ip,
            requested_transport="ssh",
            resolved_transport=None,
            ok=False,
            stage=stage,
            elapsed_seconds=time.perf_counter() - started_at,
            error=error_text,
        )
    finally:
        collector.close()


def probe_nxapi_connectivity(
    host: Dict[str, Any],
    username: str,
    password: str,
    enable_secret: str,
    logger: Logger,
    timeout: float = DEFAULT_CONNECT_CHECK_TIMEOUT,
) -> ConnectCheckResult:
    """
    Validate NX-API reachability plus authentication with a lightweight command.
    """
    hostname = str(host["hostname"])
    ip = str(host["ip"])
    device_type = str(host.get("device_type") or host.get("os_type") or "unknown").strip().lower()
    started_at = time.perf_counter()
    collector = NxapiCollector(host, username, password, enable_secret, logger)
    tcp_errors: list[str] = []
    for scheme in collector._schemes:
        port = 443 if scheme == "https" else 80
        configured_port = os.environ.get("ALRED_NXAPI_PORT", os.environ.get("NW_TOOL_NXAPI_PORT", "")).strip()
        if configured_port:
            port = int(configured_port)
        try:
            _tcp_probe(ip, port, timeout)
            break
        except Exception as exc:
            tcp_errors.append(f"{scheme}:{port} {exc}")
    else:
        return ConnectCheckResult(
            hostname=hostname,
            ip=ip,
            requested_transport="nxapi",
            resolved_transport=None,
            ok=False,
            stage="tcp",
            elapsed_seconds=time.perf_counter() - started_at,
            error="nxapi tcp connect failed: " + "; ".join(tcp_errors),
        )

    result = collector.run_command(_get_connect_check_command(device_type), read_timeout=max(int(timeout), 1))
    if result.ok:
        return ConnectCheckResult(
            hostname=hostname,
            ip=ip,
            requested_transport="nxapi",
            resolved_transport="nxapi",
            ok=True,
            stage="auth",
            elapsed_seconds=time.perf_counter() - started_at,
        )
    return ConnectCheckResult(
        hostname=hostname,
        ip=ip,
        requested_transport="nxapi",
        resolved_transport=None,
        ok=False,
        stage="auth",
        elapsed_seconds=time.perf_counter() - started_at,
        error=result.error or result.output or "unknown nxapi error",
    )


def probe_transport_connectivity(
    host: Dict[str, Any],
    username: str,
    password: str,
    enable_secret: str,
    logger: Logger,
    transport: TransportType,
    timeout: float = DEFAULT_CONNECT_CHECK_TIMEOUT,
) -> ConnectCheckResult:
    """
    Validate connectivity/authentication for the requested transport mode.
    """
    if transport == "ssh":
        return probe_ssh_connectivity(host, username, password, enable_secret, logger, timeout=timeout)

    if transport == "nxapi":
        if is_nxos_host(host):
            return probe_nxapi_connectivity(host, username, password, enable_secret, logger, timeout=timeout)
        result = probe_ssh_connectivity(host, username, password, enable_secret, logger, timeout=timeout)
        result.requested_transport = "nxapi"
        return result

    if is_nxos_host(host):
        nxapi_result = probe_nxapi_connectivity(host, username, password, enable_secret, logger, timeout=timeout)
        if nxapi_result.ok:
            nxapi_result.requested_transport = "auto"
            return nxapi_result
        ssh_result = probe_ssh_connectivity(host, username, password, enable_secret, logger, timeout=timeout)
        ssh_result.requested_transport = "auto"
        if ssh_result.ok:
            ssh_result.fallback_from = "nxapi"
            return ssh_result
        ssh_result.fallback_from = "nxapi"
        if not ssh_result.error and nxapi_result.error:
            ssh_result.error = nxapi_result.error
        return ssh_result

    result = probe_ssh_connectivity(host, username, password, enable_secret, logger, timeout=timeout)
    result.requested_transport = "auto"
    return result
