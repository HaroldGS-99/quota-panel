"""Read-only quota adapters. No inference requests and no reset redemption."""
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from model import ProviderError, quota, remaining_percent, result, timestamp, window_label

ACTIVE_CHILDREN = set()


def executable(name, override=""):
    if override:
        if Path(override).is_file() and os.access(override, os.X_OK):
            return override
        raise ProviderError("unavailable", f"Revisa la ruta de {name} en Preferencias")
    found = shutil.which(name)
    if found:
        return found
    candidates = [Path.home() / ".local/bin" / name, Path.home() / ".opencode/bin" / name]
    candidates += sorted((Path.home() / ".nvm/versions/node").glob(f"*/bin/{name}"), reverse=True)
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    raise ProviderError("unavailable", f"Instala {name} o indica su ruta en Preferencias")


def http_json(url, token=None, body=None, form=None):
    headers = {"Accept": "application/json", "User-Agent": "quota-panel/1.0"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=data, headers=headers)
    # Do not forward credentials through redirects.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(request, timeout=8) as response:
        data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ProviderError("unavailable", "Respuesta de cuotas demasiado grande")
        return json.loads(data)


def normalize_codex(data):
    buckets = data.get("rateLimitsByLimitId") or {"codex": data.get("rateLimits")}
    rows = []
    for bucket_id, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        group = bucket.get("limitName") or (None if bucket_id == "codex" else bucket_id)
        for kind in ("primary", "secondary"):
            window = bucket.get(kind)
            if not isinstance(window, dict):
                continue
            minutes = window.get("windowDurationMins")
            rows.append(quota(f"{bucket_id}:{kind}", window_label(minutes),
                              window.get("usedPercent"), window.get("resetsAt"), minutes, group))
    resets = data.get("rateLimitResetCredits") or {}
    count = resets.get("availableCount")
    count = count if isinstance(count, int) and not isinstance(count, bool) and count >= 0 else None
    return result("codex", rows, count)


def codex(config):
    proc = subprocess.Popen([executable("codex", config.get("codexPath", "")), "app-server", "--stdio"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    ACTIVE_CHILDREN.add(proc)
    try:
        def send(message):
            proc.stdin.write((json.dumps(message) + "\n").encode())
            proc.stdin.flush()
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "quota_panel", "version": "1.0"},
            "capabilities": {"experimentalApi": True}}})
        deadline = time.monotonic() + 18
        buffer = b""
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                if not selector.select(max(0, deadline - time.monotonic())):
                    break
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                buffer += chunk
                if len(buffer) > 2_000_000:
                    break
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    message = json.loads(line)
                    if message.get("id") == 1:
                        if "error" in message:
                            raise ProviderError("unavailable", "Actualiza Codex: protocolo no compatible")
                        send({"method": "initialized"})
                        send({"id": 2, "method": "account/rateLimits/read"})
                    if message.get("id") == 2:
                        if "error" in message:
                            raise ProviderError("auth", "Inicia sesión en Codex con tu cuenta ChatGPT")
                        return normalize_codex(message["result"])
        raise ProviderError("offline", "Codex no respondió a tiempo")
    finally:
        stop_child(proc)
        ACTIVE_CHILDREN.discard(proc)
        proc.stdin.close()
        proc.stdout.close()


def stop_child(proc):
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=2)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=2)


def normalize_opencode(data):
    usage = data.get("usage") or {}
    rows = []
    windows = (("rolling", "5 horas", 300), ("weekly", "Semanal", 10080), ("monthly", "Mensual", None))
    def append_windows(values, group=None):
        for key, label, minutes in windows:
            item = values.get(key)
            if isinstance(item, dict):
                rows.append(quota(f"{group or 'go'}:{key}", label, item.get("percent"),
                                  item.get("resetsAt"), minutes, group))
    append_windows(usage)
    models = data.get("models") or usage.get("models") or {}
    if isinstance(models, dict):
        for model, info in models.items():
            if isinstance(info, dict):
                append_windows(info.get("usage") or info, model)
    return result("opencode", rows)


def opencode(config):
    base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    path = base / "opencode/auth.json"
    if not path.is_file():
        raise ProviderError("auth", "Conecta OpenCode Go usando /connect en OpenCode")
    entry = json.loads(path.read_text()).get("opencode-go") or {}
    token = entry.get("key") if entry.get("type") == "api" else None
    if not token:
        raise ProviderError("auth", "Conecta OpenCode Go usando /connect en OpenCode")
    return normalize_opencode(http_json("https://opencode.ai/zen/go/v1/usage", token))


def normalize_antigravity(data):
    """Use actual shared summary groups; never add model percentages."""
    rows = []
    for group in data.get("groups", []):
        name = group.get("displayName") or group.get("name", "")
        if "gemini" not in name.lower():
            continue
        for item in group.get("buckets", []):
            window = item.get("window") or item.get("displayName") or "Cuota"
            text = str(window).lower().replace('_', ' ').replace('-', ' ')
            minutes = 10080 if ("week" in text or "seman" in text) else 300 if ("five hour" in text or "5h" in text or "5 hour" in text or "5 hora" in text or text == "18000s" or text == "pt5h") else None
            label = window_label(minutes) if minutes else str(window)
            rows.append(quota(item.get("bucketId") or item.get("id", label), label,
                              remaining_percent(item.get("remaining_fraction", item.get("remainingFraction"))),
                              item.get("reset_time", item.get("resetTime")), minutes, "Gemini Models", item.get("disabled", False)))
    if rows:
        return result("antigravity", rows)
    # Some versions return ungrouped buckets. Only accept buckets explicitly named Gemini.
    for item in data.get("buckets", []):
        if "gemini" in (str(item.get("displayName", "")) + str(item.get("bucketId", ""))).lower():
            rows.append(quota(item.get("bucketId", "gemini"), item.get("window") or "Cuota Gemini",
                              remaining_percent(item.get("remaining_fraction", item.get("remainingFraction"))), item.get("resetTime"),
                              group="Gemini Models", disabled=item.get("disabled", False)))
    return result("antigravity", rows, message=None if rows else "El servicio no devolvió el grupo Gemini")



def antigravity(config):
    """Invoke the CLI's built-in quota command; no model turn or custom OAuth client."""
    base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    directory = base / "quota-panel/agy"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = dict(os.environ, AGY_CLI_DISABLE_AUTO_UPDATE="1")
    proc = subprocess.Popen([executable("agy", config.get("agyPath", "")),
                             "--print", "/usage", "--output-format", "json"],
                            cwd=directory, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    ACTIVE_CHILDREN.add(proc)
    try:
        try:
            output, _ = proc.communicate(timeout=25)
        except subprocess.TimeoutExpired:
            raise ProviderError("offline", "agy no respondió a tiempo") from None
        if len(output) > 2_000_000:
            raise ProviderError("unavailable", "Respuesta de cuotas demasiado grande")
        try:
            data = json.loads(output)
        except (ValueError, UnicodeError):
            raise ProviderError("unavailable", "Actualiza agy o revisa su inicio de sesión") from None
        if not isinstance(data, dict) or data.get("status") != "SUCCESS":
            raise ProviderError("auth", "Abre agy y comprueba su inicio de sesión con /usage")
        command = data.get("command") or {}
        if (proc.returncode != 0 or command.get("name") not in ("usage", "quota")
                or data.get("num_turns") != 0 or not isinstance(command.get("data"), dict)):
            raise ProviderError("unavailable", "Actualiza agy: el formato de /usage cambió")
        return normalize_antigravity(command["data"])
    finally:
        stop_child(proc)
        ACTIVE_CHILDREN.discard(proc)
        proc.stdout.close()
