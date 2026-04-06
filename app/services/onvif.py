from __future__ import annotations

import json
import logging
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

import httpx
from onvif import ONVIFClient, ONVIFDiscovery

log = logging.getLogger("app.onvif")

ONVIF_PORT_CANDIDATES: tuple[tuple[int, bool], ...] = (
    (80, False),
    (2020, False),
    (8080, False),
    (8899, False),
    (443, True),
    (8443, True),
)
RTSP_PORT_CANDIDATES = (554, 8554)
HTTP_PORT_CANDIDATES: tuple[tuple[int, bool], ...] = ((80, False), (8080, False), (443, True), (8443, True))


class ONVIFServiceError(RuntimeError):
    pass


@dataclass(slots=True)
class ProbeResult:
    name: str | None
    ip_address: str | None
    connection_kind: str
    protocols: list[str]
    supports_ptz: bool
    ptz_capabilities: dict[str, bool] | None
    onvif_profile_token: str | None
    endpoints: list[dict[str, Any]]
    device_metadata: dict[str, Any] | None
    presets: list[dict[str, Any]]
    warnings: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ip_address": self.ip_address,
            "connection_kind": self.connection_kind,
            "protocols": self.protocols,
            "supports_ptz": self.supports_ptz,
            "ptz_capabilities": self.ptz_capabilities,
            "onvif_profile_token": self.onvif_profile_token,
            "endpoints": self.endpoints,
            "device_metadata": self.device_metadata,
            "presets": self.presets,
            "warnings": self.warnings,
        }


def load_device_metadata(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def dump_device_metadata(data: dict[str, Any] | None) -> str | None:
    if not data:
        return None
    return json.dumps(data, ensure_ascii=False)


def endpoint_kinds(endpoints: list[Any]) -> list[str]:
    kinds: set[str] = set()
    for endpoint in endpoints:
        kind = getattr(endpoint, "endpoint_kind", None)
        if kind is None and isinstance(endpoint, dict):
            kind = endpoint.get("endpoint_kind")
        if kind:
            kinds.add(str(kind))
    return sorted(kinds)


def endpoint_has_onvif(endpoints: list[Any]) -> bool:
    return "onvif" in endpoint_kinds(endpoints)


def _default_ptz_capabilities(supports_ptz: bool, presets: bool = False) -> dict[str, bool]:
    return {
        "pan_tilt": bool(supports_ptz),
        "zoom": False,
        "home": False,
        "presets": bool(presets),
    }


def _get_object_value(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _space_exists(container: Any, *names: str) -> bool:
    for name in names:
        value = _get_object_value(container, name)
        if isinstance(value, list) and value:
            return True
        if value not in (None, [], (), {}):
            return True
    return False


def read_ptz_capabilities(metadata: dict[str, Any] | None, supports_ptz: bool) -> dict[str, bool]:
    stored = metadata.get("ptz_capabilities") if isinstance(metadata, dict) else None
    if isinstance(stored, dict):
        base = _default_ptz_capabilities(supports_ptz)
        for key in base:
            if key in stored:
                base[key] = bool(stored[key])
        return base
    return _default_ptz_capabilities(supports_ptz)


def build_authenticated_url(url: str, username: str | None, password: str | None) -> str:
    if not username:
        return url
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        return url
    user = quote(username, safe="")
    pwd = quote(password or "", safe="")
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{user}:{pwd}@{host}"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def primary_stream_url(stream_url: str | None, endpoints: list[Any]) -> str | None:
    candidates: list[tuple[int, str]] = []
    for endpoint in endpoints:
        kind = getattr(endpoint, "endpoint_kind", None)
        url = getattr(endpoint, "endpoint_url", None)
        is_primary = getattr(endpoint, "is_primary", None)
        if isinstance(endpoint, dict):
            kind = endpoint.get("endpoint_kind", kind)
            url = endpoint.get("endpoint_url", url)
            is_primary = endpoint.get("is_primary", is_primary)
        if not kind or not url:
            continue
        weight = 0
        if kind == "rtsp":
            weight = 100
        elif kind == "http":
            weight = 50
        elif kind == "onvif":
            weight = 10
        if is_primary:
            weight += 1000
        candidates.append((weight, str(url)))
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]
    return stream_url


def probe_port(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def detect_plain_protocols(host: str, timeout: float = 1.5) -> tuple[list[str], list[str]]:
    protocols: list[str] = []
    warnings: list[str] = []
    if any(probe_port(host, port, timeout=timeout) for port in RTSP_PORT_CANDIDATES):
        protocols.append("rtsp")
    http_found = False
    for port, use_https in HTTP_PORT_CANDIDATES:
        if not probe_port(host, port, timeout=timeout):
            continue
        http_found = True
        try:
            scheme = "https" if use_https else "http"
            httpx.get(f"{scheme}://{host}:{port}", timeout=2.0, verify=False)
        except Exception:
            pass
    if http_found:
        protocols.append("http")
    if "rtsp" in protocols and "http" not in protocols:
        warnings.append("RTSP-порт обнаружен, но путь потока без ONVIF придётся уточнить вручную.")
    return protocols, warnings


def parse_scope_name(scopes: list[str]) -> str | None:
    for scope in scopes:
        if "name/" in scope:
            return scope.split("name/", 1)[1].replace("_", " ")
    return None


def discover_onvif_devices(timeout: int = 4, interface: str | None = None) -> list[dict[str, Any]]:
    discovery = ONVIFDiscovery(timeout=timeout, interface=interface)
    devices = discovery.discover()
    out: list[dict[str, Any]] = []
    for device in devices:
        scopes = [str(item) for item in device.get("scopes") or []]
        out.append(
            {
                "host": device.get("host"),
                "port": device.get("port"),
                "use_https": bool(device.get("use_https")),
                "xaddrs": list(device.get("xaddrs") or []),
                "types": list(device.get("types") or []),
                "scopes": scopes,
                "name": parse_scope_name(scopes),
            }
        )
    return out


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _extract_uri(result: Any) -> str | None:
    if isinstance(result, dict):
        return _coerce_str(result.get("Uri") or result.get("URI"))
    return _coerce_str(getattr(result, "Uri", None) or getattr(result, "URI", None))


def _get_profile_token(profile: Any) -> str | None:
    if isinstance(profile, dict):
        return _coerce_str(profile.get("token") or profile.get("Token"))
    return _coerce_str(getattr(profile, "token", None) or getattr(profile, "Token", None))


def _has_ptz_config(profile: Any) -> bool:
    if isinstance(profile, dict):
        return profile.get("PTZConfiguration") is not None
    return getattr(profile, "PTZConfiguration", None) is not None


def _service_xaddr(client: ONVIFClient, keyword: str) -> str | None:
    services = getattr(client, "services", None) or []
    keyword = keyword.lower()
    for service in services:
        namespace = str(getattr(service, "Namespace", "") or "").lower()
        xaddr = _coerce_str(getattr(service, "XAddr", None))
        if keyword in namespace and xaddr:
            return xaddr
    return None


def _read_presets(client: ONVIFClient, profile_token: str | None) -> list[dict[str, Any]]:
    if not profile_token:
        return []
    try:
        presets = client.ptz().GetPresets(ProfileToken=profile_token) or []
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for preset in presets:
        if isinstance(preset, dict):
            name = _coerce_str(preset.get("Name")) or "Preset"
            token = _coerce_str(preset.get("token") or preset.get("PresetToken"))
        else:
            name = _coerce_str(getattr(preset, "Name", None)) or "Preset"
            token = _coerce_str(getattr(preset, "token", None) or getattr(preset, "PresetToken", None))
        out.append({"name": name, "preset_token": token})
    return out


def _extract_ptz_capabilities(
    client: ONVIFClient,
    profile: Any | None,
    profile_token: str | None,
    supports_ptz: bool,
    has_presets: bool,
) -> dict[str, bool]:
    capabilities = _default_ptz_capabilities(supports_ptz, presets=has_presets)
    if not supports_ptz or profile is None or not profile_token:
        return capabilities

    ptz = client.ptz()
    try:
        config = _get_object_value(profile, "PTZConfiguration")
        config_token = _coerce_str(_get_object_value(config, "token") or _get_object_value(config, "Token"))
        if config_token:
            try:
                options = ptz.GetConfigurationOptions(ConfigurationToken=config_token)
            except TypeError:
                options = ptz.GetConfigurationOptions(PTZConfigurationToken=config_token)
            spaces = _get_object_value(options, "Spaces")
            if spaces is not None:
                capabilities["pan_tilt"] = _space_exists(
                    spaces,
                    "ContinuousPanTiltVelocitySpace",
                    "RelativePanTiltTranslationSpace",
                    "AbsolutePanTiltPositionSpace",
                )
                capabilities["zoom"] = _space_exists(
                    spaces,
                    "ContinuousZoomVelocitySpace",
                    "RelativeZoomTranslationSpace",
                    "AbsoluteZoomPositionSpace",
                )
    except Exception:
        pass

    try:
        nodes = ptz.GetNodes() or []
        node = nodes[0] if nodes else None
        if node is not None:
            home_supported = _get_object_value(node, "HomeSupported")
            if home_supported is not None:
                capabilities["home"] = bool(home_supported)
            supported_spaces = _get_object_value(node, "SupportedPTZSpaces")
            if supported_spaces is not None:
                capabilities["pan_tilt"] = capabilities["pan_tilt"] or _space_exists(
                    supported_spaces,
                    "ContinuousPanTiltVelocitySpace",
                    "RelativePanTiltTranslationSpace",
                    "AbsolutePanTiltPositionSpace",
                )
                capabilities["zoom"] = capabilities["zoom"] or _space_exists(
                    supported_spaces,
                    "ContinuousZoomVelocitySpace",
                    "RelativeZoomTranslationSpace",
                    "AbsoluteZoomPositionSpace",
                )
    except Exception:
        pass

    return capabilities


def _build_media_endpoints(client: ONVIFClient, profile_token: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    endpoints: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not profile_token:
        return endpoints, warnings
    rtsp_uri = None
    snapshot_uri = None
    try:
        media2 = client.media2()
        rtsp_uri = _extract_uri(media2.GetStreamUri(Protocol="RTSP", ProfileToken=profile_token))
        snapshot_uri = _extract_uri(media2.GetSnapshotUri(ProfileToken=profile_token))
    except Exception:
        try:
            media = client.media()
            rtsp_uri = _extract_uri(
                media.GetStreamUri(
                    StreamSetup={"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}},
                    ProfileToken=profile_token,
                )
            )
        except Exception as exc:
            warnings.append(f"Не удалось получить RTSP URI через ONVIF: {exc}")
        try:
            snapshot_uri = _extract_uri(media.GetSnapshotUri(ProfileToken=profile_token))
        except Exception:
            snapshot_uri = None
    if rtsp_uri:
        endpoints.append({"endpoint_kind": "rtsp", "endpoint_url": rtsp_uri, "is_primary": True})
    if snapshot_uri:
        endpoints.append({"endpoint_kind": "http", "endpoint_url": snapshot_uri, "is_primary": not rtsp_uri})
    return endpoints, warnings


def _candidate_targets(host: str, port: int | None, use_https: bool | None, discovered: list[dict[str, Any]] | None) -> list[tuple[int, bool]]:
    targets: list[tuple[int, bool]] = []
    if port is not None:
        targets.append((port, bool(use_https)))
    if discovered:
        for item in discovered:
            if item.get("host") != host:
                continue
            item_port = item.get("port")
            if item_port is None:
                continue
            target = (int(item_port), bool(item.get("use_https")))
            if target not in targets:
                targets.append(target)
    for candidate in ONVIF_PORT_CANDIDATES:
        if candidate not in targets:
            targets.append(candidate)
    return targets


def probe_camera(host: str, username: str | None = None, password: str | None = None, port: int | None = None, use_https: bool | None = None, timeout: int = 5, discovered: list[dict[str, Any]] | None = None) -> ProbeResult:
    protocols: list[str] = []
    warnings: list[str] = []
    plain_protocols, plain_warnings = detect_plain_protocols(host, timeout=max(1.0, timeout / 2))
    protocols.extend(plain_protocols)
    warnings.extend(plain_warnings)

    last_error: Exception | None = None
    for candidate_port, candidate_https in _candidate_targets(host, port, use_https, discovered):
        try:
            client = ONVIFClient(
                host,
                candidate_port,
                username or "",
                password or "",
                timeout=timeout,
                use_https=candidate_https,
                verify_ssl=False,
            )
            info = client.devicemgmt().GetDeviceInformation()
            device_info = {
                "manufacturer": _coerce_str(getattr(info, "Manufacturer", None)),
                "model": _coerce_str(getattr(info, "Model", None)),
                "firmware_version": _coerce_str(getattr(info, "FirmwareVersion", None)),
                "serial_number": _coerce_str(getattr(info, "SerialNumber", None)),
                "hardware_id": _coerce_str(getattr(info, "HardwareId", None)),
                "host": host,
                "port": candidate_port,
                "use_https": candidate_https,
                "onvif_xaddr": _service_xaddr(client, "device"),
                "media_xaddr": _service_xaddr(client, "media"),
                "ptz_xaddr": _service_xaddr(client, "ptz"),
            }
            try:
                hostname_info = client.devicemgmt().GetHostname()
                device_info["hostname"] = _coerce_str(getattr(hostname_info, "Name", None))
            except Exception:
                pass
            try:
                network_protocols = client.devicemgmt().GetNetworkProtocols() or []
                device_info["network_protocols"] = [
                    _coerce_str(getattr(item, "Name", None) if not isinstance(item, dict) else item.get("Name"))
                    for item in network_protocols
                ]
            except Exception:
                pass

            profiles: list[Any] = []
            profile_token = None
            supports_ptz = False
            try:
                profiles = list(client.media2().GetProfiles() or [])
            except Exception:
                try:
                    profiles = list(client.media().GetProfiles() or [])
                except Exception:
                    profiles = []
            if profiles:
                preferred = next((profile for profile in profiles if _has_ptz_config(profile)), profiles[0])
                profile_token = _get_profile_token(preferred)
                supports_ptz = any(_has_ptz_config(profile) for profile in profiles)
            elif client.capabilities:
                supports_ptz = getattr(client.capabilities, "PTZ", None) is not None

            endpoints = []
            onvif_xaddr = device_info.get("onvif_xaddr") or f"{'https' if candidate_https else 'http'}://{host}:{candidate_port}/onvif/device_service"
            endpoints.append({"endpoint_kind": "onvif", "endpoint_url": onvif_xaddr, "is_primary": True})
            media_endpoints, media_warnings = _build_media_endpoints(client, profile_token)
            endpoints.extend(media_endpoints)
            warnings.extend(media_warnings)

            presets = _read_presets(client, profile_token) if supports_ptz else []
            ptz_capabilities = _extract_ptz_capabilities(
                client,
                preferred if profiles else None,
                profile_token,
                supports_ptz,
                bool(presets),
            )
            device_info["ptz_capabilities"] = ptz_capabilities
            for protocol in ("onvif", "rtsp", "http"):
                if any(ep["endpoint_kind"] == protocol for ep in endpoints) and protocol not in protocols:
                    protocols.append(protocol)

            name = device_info.get("hostname") or device_info.get("model") or host
            order = {"onvif": 0, "rtsp": 1, "http": 2}
            return ProbeResult(
                name=name,
                ip_address=host,
                connection_kind="onvif",
                protocols=sorted(set(protocols), key=lambda item: order.get(item, 99)),
                supports_ptz=supports_ptz,
                ptz_capabilities=ptz_capabilities,
                onvif_profile_token=profile_token,
                endpoints=endpoints,
                device_metadata=device_info,
                presets=presets,
                warnings=warnings,
            )
        except Exception as exc:
            last_error = exc
            log.debug("ONVIF probe failed for %s:%s https=%s: %s", host, candidate_port, candidate_https, exc)

    if protocols:
        return ProbeResult(
            name=host,
            ip_address=host,
            connection_kind=protocols[0],
            protocols=protocols,
            supports_ptz=False,
            ptz_capabilities=_default_ptz_capabilities(False),
            onvif_profile_token=None,
            endpoints=[],
            device_metadata={"host": host, "note": "ONVIF probe failed; protocols inferred from open ports."},
            presets=[],
            warnings=warnings + ([f"ONVIF недоступен: {last_error}"] if last_error else []),
        )

    raise ONVIFServiceError(f"Не удалось определить камеру {host}: {last_error or 'устройство не отвечает'}")


def _camera_onvif_credentials(camera: Any) -> tuple[str, str, str, str, int, bool]:
    metadata = load_device_metadata(getattr(camera, "device_metadata", None)) or {}
    for endpoint in getattr(camera, "endpoints", []) or []:
        if endpoint.endpoint_kind != "onvif":
            continue
        endpoint_url = endpoint.endpoint_url
        host = str(metadata.get("host") or camera.ip_address or urlparse(endpoint_url).hostname or "")
        port = int(metadata.get("port") or urlparse(endpoint_url).port or 80)
        use_https = bool(metadata.get("use_https") or urlparse(endpoint_url).scheme == "https")
        return endpoint_url, endpoint.username or "", endpoint.password_secret or "", host, port, use_https
    raise ONVIFServiceError("У камеры не настроен ONVIF endpoint")


def _normalize_onvif_operation_error(action: str, exc: Exception, unsupported_message: str | None = None) -> ONVIFServiceError:
    message = str(exc).strip() or action
    if unsupported_message and "ActionNotSupported" in message:
        return ONVIFServiceError(unsupported_message)
    return ONVIFServiceError(f"{action}: {message}")


def camera_to_detail_payload(camera: Any) -> dict[str, Any]:
    metadata = load_device_metadata(getattr(camera, "device_metadata", None))
    endpoints = []
    for endpoint in getattr(camera, "endpoints", []) or []:
        endpoints.append(
            {
                "camera_endpoint_id": endpoint.camera_endpoint_id,
                "endpoint_kind": endpoint.endpoint_kind,
                "endpoint_url": endpoint.endpoint_url,
                "username": endpoint.username,
                "has_password": bool(endpoint.password_secret),
                "is_primary": endpoint.is_primary,
            }
        )
    return {
        "camera_id": camera.camera_id,
        "name": camera.name,
        "location": camera.location,
        "ip_address": camera.ip_address,
        "stream_url": primary_stream_url(camera.stream_url, camera.endpoints),
        "permission": "admin",
        "detection_enabled": camera.detection_enabled,
        "recording_mode": camera.recording_mode,
        "tracking_enabled": camera.tracking_enabled,
        "tracking_mode": camera.tracking_mode,
        "tracking_target_person_id": camera.tracking_target_person_id,
        "group_id": camera.group_id,
        "connection_kind": camera.connection_kind,
        "onvif_enabled": endpoint_has_onvif(camera.endpoints),
        "supports_ptz": camera.supports_ptz,
        "ptz_capabilities": read_ptz_capabilities(metadata, camera.supports_ptz),
        "onvif_profile_token": camera.onvif_profile_token,
        "device_metadata": metadata,
        "endpoint_kinds": endpoint_kinds(camera.endpoints),
        "endpoints": endpoints,
    }


def ptz_relative_move(camera: Any, pan: float = 0.0, tilt: float = 0.0, zoom: float = 0.0, speed: float | None = None) -> dict[str, Any]:
    _endpoint_url, username, password, host, port, use_https = _camera_onvif_credentials(camera)
    if not host or not camera.onvif_profile_token:
        raise ONVIFServiceError("Для PTZ не настроен profile token или host")
    client = ONVIFClient(host, port, username, password, timeout=8, use_https=use_https, verify_ssl=False)
    translation: dict[str, Any] = {}
    if pan or tilt:
        translation["PanTilt"] = {"x": float(pan), "y": float(tilt)}
    if zoom:
        translation["Zoom"] = {"x": float(zoom)}
    speed_payload = None
    if speed is not None:
        speed_payload = {}
        if pan or tilt:
            speed_payload["PanTilt"] = {"x": float(speed), "y": float(speed)}
        if zoom:
            speed_payload["Zoom"] = {"x": float(speed)}
    try:
        client.ptz().RelativeMove(ProfileToken=camera.onvif_profile_token, Translation=translation, Speed=speed_payload)
    except Exception as exc:
        raise _normalize_onvif_operation_error("Не удалось выполнить относительное PTZ-перемещение", exc) from exc
    return {"ok": True}


def ptz_continuous_move(camera: Any, pan: float = 0.0, tilt: float = 0.0, zoom: float = 0.0, timeout_seconds: float | None = 0.4) -> dict[str, Any]:
    _endpoint_url, username, password, host, port, use_https = _camera_onvif_credentials(camera)
    if not host or not camera.onvif_profile_token:
        raise ONVIFServiceError("Для PTZ не настроен profile token или host")
    velocity: dict[str, Any] = {}
    if pan or tilt:
        velocity["PanTilt"] = {"x": float(pan), "y": float(tilt)}
    if zoom:
        velocity["Zoom"] = {"x": float(zoom)}
    client = ONVIFClient(host, port, username, password, timeout=8, use_https=use_https, verify_ssl=False)
    if timeout_seconds is not None:
        duration = max(float(timeout_seconds or 0.1), 0.1)
        try:
            client.ptz().ContinuousMove(ProfileToken=camera.onvif_profile_token, Velocity=velocity, Timeout=f"PT{duration:.1f}S")
            return {"ok": True}
        except Exception as exc:
            log.warning(
                "PTZ ContinuousMove with Timeout failed for camera %s, retrying without Timeout: %s",
                getattr(camera, "camera_id", "?"),
                exc,
            )
            client = ONVIFClient(host, port, username, password, timeout=8, use_https=use_https, verify_ssl=False)
    try:
        client.ptz().ContinuousMove(ProfileToken=camera.onvif_profile_token, Velocity=velocity)
    except Exception as exc:
        raise _normalize_onvif_operation_error("Не удалось выполнить непрерывное PTZ-перемещение", exc) from exc
    return {"ok": True}


def ptz_absolute_move(camera: Any, pan: float | None = None, tilt: float | None = None, zoom: float | None = None, speed: float | None = None) -> dict[str, Any]:
    _endpoint_url, username, password, host, port, use_https = _camera_onvif_credentials(camera)
    if not host or not camera.onvif_profile_token:
        raise ONVIFServiceError("Для PTZ не настроен profile token или host")
    client = ONVIFClient(host, port, username, password, timeout=8, use_https=use_https, verify_ssl=False)
    position: dict[str, Any] = {}
    if pan is not None or tilt is not None:
        position["PanTilt"] = {"x": float(pan or 0.0), "y": float(tilt or 0.0)}
    if zoom is not None:
        position["Zoom"] = {"x": float(zoom)}
    speed_payload = None
    if speed is not None:
        speed_payload = {}
        if pan is not None or tilt is not None:
            speed_payload["PanTilt"] = {"x": float(speed), "y": float(speed)}
        if zoom is not None:
            speed_payload["Zoom"] = {"x": float(speed)}
    try:
        client.ptz().AbsoluteMove(ProfileToken=camera.onvif_profile_token, Position=position, Speed=speed_payload)
    except Exception as exc:
        raise _normalize_onvif_operation_error("Не удалось выполнить абсолютное PTZ-перемещение", exc) from exc
    return {"ok": True}


def ptz_stop(camera: Any) -> dict[str, Any]:
    _endpoint_url, username, password, host, port, use_https = _camera_onvif_credentials(camera)
    if not host or not camera.onvif_profile_token:
        raise ONVIFServiceError("Для PTZ не настроен profile token или host")
    client = ONVIFClient(host, port, username, password, timeout=8, use_https=use_https, verify_ssl=False)
    try:
        client.ptz().Stop(ProfileToken=camera.onvif_profile_token, PanTilt=True, Zoom=True)
    except Exception as exc:
        raise _normalize_onvif_operation_error("Не удалось остановить PTZ-движение", exc) from exc
    return {"ok": True}


def goto_home(camera: Any) -> dict[str, Any]:
    _endpoint_url, username, password, host, port, use_https = _camera_onvif_credentials(camera)
    if not host or not camera.onvif_profile_token:
        raise ONVIFServiceError("Для PTZ не настроен profile token или host")
    client = ONVIFClient(host, port, username, password, timeout=8, use_https=use_https, verify_ssl=False)
    try:
        client.ptz().GotoHomePosition(ProfileToken=camera.onvif_profile_token)
    except Exception as exc:
        raise _normalize_onvif_operation_error(
            "Не удалось перейти в домашнее положение",
            exc,
            unsupported_message="Камера не поддерживает переход в домашнее положение.",
        ) from exc
    return {"ok": True}


def goto_preset(camera: Any, preset_token: str) -> dict[str, Any]:
    _endpoint_url, username, password, host, port, use_https = _camera_onvif_credentials(camera)
    if not host or not camera.onvif_profile_token:
        raise ONVIFServiceError("Для PTZ не настроен profile token или host")
    client = ONVIFClient(host, port, username, password, timeout=8, use_https=use_https, verify_ssl=False)
    try:
        client.ptz().GotoPreset(ProfileToken=camera.onvif_profile_token, PresetToken=preset_token)
    except Exception as exc:
        raise _normalize_onvif_operation_error("Не удалось перейти к пресету", exc) from exc
    return {"ok": True}


def set_preset(camera: Any, name: str, preset_token: str | None = None) -> str:
    _endpoint_url, username, password, host, port, use_https = _camera_onvif_credentials(camera)
    if not host or not camera.onvif_profile_token:
        raise ONVIFServiceError("Для PTZ не настроен profile token или host")
    client = ONVIFClient(host, port, username, password, timeout=8, use_https=use_https, verify_ssl=False)
    try:
        result = client.ptz().SetPreset(ProfileToken=camera.onvif_profile_token, PresetName=name, PresetToken=preset_token)
    except Exception as exc:
        raise _normalize_onvif_operation_error("Не удалось создать пресет", exc) from exc
    token = _coerce_str(getattr(result, "PresetToken", None) if not isinstance(result, dict) else result.get("PresetToken")) or _coerce_str(result)
    if not token:
        raise ONVIFServiceError("Камера не вернула токен пресета")
    return token


def remove_preset(camera: Any, preset_token: str) -> dict[str, Any]:
    _endpoint_url, username, password, host, port, use_https = _camera_onvif_credentials(camera)
    if not host or not camera.onvif_profile_token:
        raise ONVIFServiceError("Для PTZ не настроен profile token или host")
    client = ONVIFClient(host, port, username, password, timeout=8, use_https=use_https, verify_ssl=False)
    try:
        client.ptz().RemovePreset(ProfileToken=camera.onvif_profile_token, PresetToken=preset_token)
    except Exception as exc:
        raise _normalize_onvif_operation_error("Не удалось удалить пресет", exc) from exc
    return {"ok": True}
