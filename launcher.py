"""Одна точка входа Python / EXE: окно, API и воркеры.

Дочерний процесс запускает тот же EXE с --service. freeze_support обязателен
для multiprocessing на Windows: иначе рендер запустил бы ещё одно окно.
"""

import multiprocessing
import os
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()

import json
import logging
import subprocess
import time
import httpx
import psutil
from backend.config import BASE_URL, FROZEN, PORT, ROOT, STORAGE


def migrate():
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    command.upgrade(config, "head")


def start_process(service, log_name):
    command = (
        [sys.executable, "--service", service]
        if FROZEN
        else [sys.executable, str(ROOT / "launcher.py"), "--service", service]
    )
    with (STORAGE / "logs" / log_name).open("a", encoding="utf-8") as log_file:
        return subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )


def stop_process(process):
    try:
        owned = psutil.Process(process.pid)
        children = owned.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        owned.terminate()
        _, alive = psutil.wait_procs([owned, *children], timeout=5)
        for child in alive:
            child.kill()
    except psutil.NoSuchProcess:
        pass


def run_service(service):
    logging.basicConfig(
        filename=STORAGE / "logs" / f"{service}.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    if service == "api":
        import uvicorn
        from backend.api import app

        uvicorn.run(app, host="127.0.0.1", port=PORT, access_log=False, log_config=None)
    elif service == "worker":
        from backend.worker import main

        main()
    else:
        raise ValueError("Неизвестная служба")


def main():
    os.chdir(ROOT)
    if "--service" in sys.argv:
        run_service(sys.argv[sys.argv.index("--service") + 1])
        return
    if "--migrate" in sys.argv:
        migrate()
        return
    try:
        response = httpx.get(BASE_URL + "/api/health", timeout=1, trust_env=False)
        if response.status_code == 200:
            raise RuntimeError(f"Порт {PORT} уже занят. Если CLIP TRIBUNE запущен, используйте его окно.")
    except httpx.RequestError:
        pass
    migrate()
    api = start_process("api", "api.log")
    worker = None
    try:
        for _ in range(150):
            if api.poll() is not None:
                raise RuntimeError(f"Сервер не запустился. Подробности: {STORAGE / 'logs' / 'api.log'}")
            try:
                if httpx.get(BASE_URL + "/api/health", timeout=1, trust_env=False).is_success:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            raise RuntimeError("Сервер не ответил за отведённое время")
        worker = start_process("worker", "worker.log")
        processes = [psutil.Process(os.getpid()), psutil.Process(api.pid), psutil.Process(worker.pid)]
        (STORAGE / "processes.json").write_text(
            json.dumps([dict(pid=p.pid, created=p.create_time()) for p in processes]), encoding="utf-8"
        )
        if "--self-check" in sys.argv:
            from scripts.packaged_check import run

            run(sys.argv[sys.argv.index("--self-check") + 1])
        else:
            from desktop.app import main as desktop_main

            desktop_main()
    finally:
        try:
            token = (STORAGE / ".api-token").read_text(encoding="utf-8")
            httpx.post(
                BASE_URL + "/api/control/stop", headers={"X-Clip-Tribune": token}, timeout=3, trust_env=False
            )
            time.sleep(1)
        except OSError, httpx.HTTPError:
            pass
        if worker:
            stop_process(worker)
        stop_process(api)
        (STORAGE / "processes.json").unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        import traceback

        (STORAGE / "logs" / "startup-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        if "--service" not in sys.argv and "--self-check" not in sys.argv:
            from tkinter import Tk, messagebox

            root = Tk()
            root.withdraw()
            messagebox.showerror("CLIP TRIBUNE", str(error), parent=root)
            root.destroy()
        elif sys.stderr:
            print(f"CLIP TRIBUNE: {error}", file=sys.stderr)
        raise SystemExit(1) from error
