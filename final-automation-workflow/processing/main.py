import os
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as ThreadTimeoutError

from utils.text_utils import print_debug
from utils.browser_utils import monitor_and_kill_outlook
from config import LOGS_DIR_PATH, DOMAINS_TXT_PATH
from processing.domain_processor import process_domain
from utils.report_utils import generate_summary_csv


def main():
    print_debug("Starting scraping process")

    # Read domain list from txt file
    with open(DOMAINS_TXT_PATH, "r", encoding="utf-8") as f:
        domains = [line.strip() for line in f if line.strip()]

    for domain in domains:
        print_debug(f"Processing domain: {domain}")
        monitor_and_kill_outlook()

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(process_domain, "https://" + domain)
                log = future.result(timeout=300)
        except TimeoutError:
            log = {
                'domain': domain,
                'email_extraction': {
                    'method_used': 'NLP',
                    'emails_found': [],
                },
                'token_usage': {
                    'tokens_used': 0,
                    'summarize_calls': 0,
                    'estimated_cost_usd': 0
                },
                'used_recovery': False,
                'timed_out': True,
                'form_detected': False,
                'form_page_urls': [],
                'chosen_form': {},
                'form_submission_log': {
                    'url': '',
                    'filled_fields': [],
                    'submit_clicked': False,
                    'captcha_present': False,
                    'captcha_solved': False,
                    'captcha_fallback_used': False,
                    'captcha_error': '',
                    'errors': []
                }
            }
            print_debug(f"[TIMEOUT] Skipped {domain} after full limit.")
        except Exception as e:
            print_debug(f"[ERROR] Failed to process {domain}: {e}")
            continue

        # Write the final log to file (includes form submission log if applicable)
        log_path = os.path.join(
            LOGS_DIR_PATH, f"{domain.replace('.', '_')}.json")
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(log, f, indent=2)
            print_debug(f"{domain} completed and log saved.")

    print_debug("Scraping completed for all domains")
    generate_summary_csv()


main()
