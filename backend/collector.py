#!/usr/bin/env python3
"""One bounded collection per invocation; stdout contains no credentials."""
import concurrent.futures
import json
import os
import signal
import sys
import urllib.error

from model import NAMES, ProviderError
import providers


def collect_one(provider, config):
    try:
        return getattr(providers, provider)(config)
    except ProviderError as error:
        status, message = error.status, error.message
    except urllib.error.HTTPError as error:
        status, message = {
            401: ("auth", "Sesión vencida: vuelve a iniciar sesión en la aplicación"),
            403: ("unavailable", "La cuenta o el plan no permiten consultar esta cuota"),
            429: ("throttled", "Demasiadas consultas; se reintentará más tarde"),
        }.get(error.code, ("offline", "El servicio de cuotas no está disponible"))
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        status, message = "offline", "Sin conexión; se conservará el último dato"
    except Exception:
        # Never expose exception text: URLs, server errors and subprocess output can contain secrets.
        status, message = "unavailable", "No se pudo leer la cuota; revisa la sesión y las dependencias"
    return {"id": provider, "name": NAMES[provider], "status": status, "message": message,
            "updatedAt": None, "quotas": [], "resetsAvailable": None}


def shutdown(signum, frame):
    for proc in list(providers.ACTIVE_CHILDREN):
        providers.stop_child(proc)
    # ThreadPoolExecutor would otherwise wait for HTTP workers during interpreter shutdown.
    os._exit(0)


def main():
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    config = json.loads(sys.stdin.readline() or "{}")
    selected = config.pop("providers", list(NAMES))
    selected = [p for p in selected if p in NAMES]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(collect_one, p, config) for p in selected]
        for future in concurrent.futures.as_completed(futures):
            print(json.dumps(future.result(), allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
