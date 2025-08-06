import time
import os
import psutil
import contextlib


def monitor_and_kill_outlook():
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] and 'outlook' in proc.info['name'].lower():
            print("[WARNING] Outlook detected — killing process.")
            proc.kill()


def scroll_to_bottom(driver, timeout=60):
    start_time = time.time()
    last_height = driver.execute_script("return document.body.scrollHeight")

    while True:
        driver.execute_script(
            "window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        new_height = driver.execute_script("return document.body.scrollHeight")

        if new_height == last_height:
            break
        last_height = new_height

        if time.time() - start_time > timeout:
            print("[WARN] Scrolling timeout exceeded. Proceeding with partial content.")
            break


@contextlib.contextmanager
def suppress_output():
    with open(os.devnull, "w") as fnull:
        with contextlib.redirect_stdout(fnull), contextlib.redirect_stderr(fnull):
            yield
