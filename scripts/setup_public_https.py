#!/usr/bin/env python3
"""Configure CCTV public HTTPS endpoint with nginx and Let's Encrypt."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import socket
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE_PATH = ROOT / ".env.example"


def _read_env(path: Path, *, create: bool = True) -> list[str]:
    if not path.exists():
        if not create:
            if ENV_EXAMPLE_PATH.exists():
                return ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines()
            return []
        if ENV_EXAMPLE_PATH.exists():
            path.write_text(ENV_EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            path.write_text("", encoding="utf-8")
    return path.read_text(encoding="utf-8").splitlines()


def _parse_env(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _set_env(lines: list[str], updates: dict[str, str]) -> list[str]:
    pending = dict(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in pending:
            out.append(f"{key}={pending.pop(key)}")
        else:
            out.append(line)
    if pending:
        if out and out[-1].strip():
            out.append("")
        for key, value in pending.items():
            out.append(f"{key}={value}")
    return out


def _json_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _fernet_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def _is_weak(value: str | None, minimum: int, blocked: set[str]) -> bool:
    clean = (value or "").strip()
    return len(clean) < minimum or clean.lower() in blocked


def _run(args: list[str], *, dry_run: bool) -> None:
    print("+ " + " ".join(args))
    if dry_run:
        return
    subprocess.run(args, cwd=ROOT, check=True)


def _resolve_domain(domain: str) -> list[str]:
    ips: set[str] = set()
    for family, _, _, _, sockaddr in socket.getaddrinfo(domain, 80, type=socket.SOCK_STREAM):
        if family in {socket.AF_INET, socket.AF_INET6}:
            ips.add(str(sockaddr[0]))
    return sorted(ips)


def _public_ip() -> str | None:
    try:
        with urlopen("https://api.ipify.org", timeout=5) as response:
            return response.read().decode("utf-8").strip()
    except Exception:
        return None


def _validate_domain(domain: str) -> None:
    if domain in {"localhost", "127.0.0.1"}:
        raise SystemExit("DOMAIN должен быть реальным доменом, а не localhost")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]{1,251}[a-zA-Z0-9]", domain):
        raise SystemExit("DOMAIN выглядит некорректно")


def _validate_email(email: str) -> None:
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise SystemExit("SSL_EMAIL выглядит некорректно")


def configure(args: argparse.Namespace) -> None:
    domain = args.domain.strip().lower().rstrip(".")
    email = args.email.strip()
    _validate_domain(domain)
    _validate_email(email)

    lines = _read_env(ENV_PATH, create=not (args.check_only or args.dry_run))
    current = _parse_env(lines)
    generated_admin_password = None

    updates = {
        "DOMAIN": domain,
        "SSL_EMAIL": email,
        "BACKEND_BIND": "127.0.0.1",
        "BACKEND_PORT": current.get("BACKEND_PORT") or "8001",
        "ENVIRONMENT": "production",
        "ENABLE_DOCS": "false",
        "ALLOW_DEFAULT_ADMIN": "false",
        "ALLOW_LEGACY_QUERY_TOKENS": "false",
        "NGINX_HTTP_PORT": current.get("NGINX_HTTP_PORT") or "80",
        "NGINX_HTTPS_PORT": current.get("NGINX_HTTPS_PORT") or "443",
        "NGINX_CLIENT_MAX_BODY_SIZE": current.get("NGINX_CLIENT_MAX_BODY_SIZE") or "100m",
        "ALLOWED_HOSTS": _json_list([domain, "127.0.0.1", "localhost"]),
        "CORS_ORIGINS": _json_list([f"https://{domain}"]),
    }

    if _is_weak(
        current.get("JWT_SECRET"),
        32,
        {"change-me", "changeme", "changeme-generate-with-openssl-rand-hex-32"},
    ):
        updates["JWT_SECRET"] = secrets.token_hex(32)
    if _is_weak(
        current.get("PROCESSOR_API_KEY"),
        24,
        {"processor-secret-key-2026", "changeme", "changeme-generate-with-openssl-rand-hex-24"},
    ):
        updates["PROCESSOR_API_KEY"] = secrets.token_urlsafe(32)
    if not current.get("TOTP_ENCRYPTION_KEY"):
        updates["TOTP_ENCRYPTION_KEY"] = _fernet_key()
    if not current.get("BOOTSTRAP_ADMIN_PASSWORD"):
        generated_admin_password = secrets.token_urlsafe(24)
        updates["BOOTSTRAP_ADMIN_PASSWORD"] = generated_admin_password

    try:
        resolved = _resolve_domain(domain)
    except Exception as exc:
        resolved = []
        print(f"WARN: DNS lookup не выполнен: {exc}")
    public_ip = _public_ip()
    if resolved:
        print(f"DNS {domain}: {', '.join(resolved)}")
    if public_ip:
        print(f"Публичный IP этого сервера: {public_ip}")
        if resolved and public_ip not in resolved:
            print("WARN: домен не указывает на текущий публичный IPv4. Let's Encrypt может отказать.")

    if args.check_only:
        print("Проверка завершена без изменения файлов.")
        return

    updates["NGINX_HTTPS_ENABLED"] = "false"
    rendered_env = "\n".join(_set_env(lines, updates)) + "\n"
    if args.dry_run:
        print(f"DRY-RUN: {ENV_PATH} would be updated.")
    else:
        ENV_PATH.write_text(rendered_env, encoding="utf-8")
        print(f"Обновлен {ENV_PATH}")

    _run(
        [
            "docker",
            "compose",
            "--profile",
            "core",
            "--profile",
            "with-frontend",
            "--profile",
            "public",
            "up",
            "-d",
            "--build",
            "db",
            "backend",
            "frontend",
            "nginx",
        ],
        dry_run=args.dry_run,
    )

    certbot_cmd = [
        "docker",
        "compose",
        "--profile",
        "core",
        "--profile",
        "with-frontend",
        "--profile",
        "public",
        "run",
        "--rm",
        "certbot",
        "certonly",
        "--webroot",
        "--webroot-path=/var/www/certbot",
        "--email",
        email,
        "--agree-tos",
        "--no-eff-email",
        "-d",
        domain,
    ]
    if args.staging:
        certbot_cmd.append("--staging")
    _run(certbot_cmd, dry_run=args.dry_run)

    if not args.dry_run:
        final_lines = _set_env(_read_env(ENV_PATH), {"NGINX_HTTPS_ENABLED": "true"})
        ENV_PATH.write_text("\n".join(final_lines) + "\n", encoding="utf-8")
    else:
        print(f"DRY-RUN: {ENV_PATH} would set NGINX_HTTPS_ENABLED=true.")

    _run(
        [
            "docker",
            "compose",
            "--profile",
            "core",
            "--profile",
            "with-frontend",
            "--profile",
            "public",
            "up",
            "-d",
            "--build",
            "nginx",
            "certbot",
        ],
        dry_run=args.dry_run,
    )

    print("")
    print(f"Готово: https://{domain}")
    print("Автопродление: контейнер certbot выполняет renew каждые 12 часов, nginx перезагружается периодически.")
    if generated_admin_password:
        print("")
        print("Создан BOOTSTRAP_ADMIN_PASSWORD. Сохраните его в менеджере паролей:")
        print(generated_admin_password)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True, help="Public domain, e.g. cctv.example.com")
    parser.add_argument("--email", required=True, help="Let's Encrypt account email")
    parser.add_argument("--staging", action="store_true", help="Use Let's Encrypt staging CA")
    parser.add_argument("--check-only", action="store_true", help="Only validate DNS/input")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running Docker")
    args = parser.parse_args()
    configure(args)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
