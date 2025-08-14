import os
import time
import json
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, TimeoutError as ThreadTimeoutError

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

from utils.text_utils import extract_emails_from_text, print_debug
from utils.browser_utils import monitor_and_kill_outlook, scroll_to_bottom, suppress_output
from config import CHROMEDRIVER_PATH, GPT_COST_PER_1K_TOKENS

from extraction.link_extraction import extract_links, is_relevant_link
from extraction.page_extraction import extract_text_from_page, nested_subpage_recovery
from gpt.form_selector import process_detected_forms
from extraction.form_extraction import parse_form_fields
from form_submit.utils import form_is_fillable


def process_domain(domain_url):
    detected_forms_dict = {}

    log = {
        'domain': domain_url,
        'email_extraction': {
            'method_used': None,
            'emails_found': [],
        },
        'token_usage': {
            'tokens_used': 0,
            'summarize_calls': 0,
            'estimated_cost_usd': 0.0
        },
        'used_recovery': False,
        'timed_out': False,
        'form_detected': False,
        'form_page_urls': [],
        'chosen_form': {}
    }

    start_time = time.time()
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])

    with suppress_output():
        driver = webdriver.Chrome(service=Service(
            CHROMEDRIVER_PATH), options=options)

    driver.get(domain_url)
    time.sleep(3)

    raw_links = extract_links(driver, restrict_to_header_footer=True)
    found_links = {}
    seen_urls = set()
    relevant_link_texts = []

    for text, href in raw_links:
        abs_url = urljoin(domain_url, href)
        if abs_url in seen_urls:
            continue
        if is_relevant_link(text):
            relevant_link_texts.append(text)
            found_links[text] = abs_url
            seen_urls.add(abs_url)

    print(f"\nTotal relevant links found: {len(relevant_link_texts)}")
    print(f"Relevance result: {relevant_link_texts}")

    if not found_links:
        fallback_links = extract_links(driver, restrict_to_header_footer=False)
        for text, href in fallback_links:
            abs_url = urljoin(domain_url, href)
            if abs_url in seen_urls:
                continue
            if is_relevant_link(text):
                found_links[text] = abs_url
                seen_urls.add(abs_url)

    page_texts = {}

    for i, (page_name, page_url) in enumerate(found_links.items()):
        if time.time() - start_time > 240:
            log['timed_out'] = True
            print(f"[TIME LIMIT] Partial scrape used for {domain_url}.")
            break
        try:
            driver.get(page_url)
            scroll_to_bottom(driver)
            text, extracted_forms = extract_text_from_page(
                driver, i + 1, page_url, log)
            if text.strip():
                page_texts[page_name] = text
            form_index = len(detected_forms_dict) + 1
            for form in extracted_forms.values():
                html, text, url = form
                parsed_fields = parse_form_fields(html)

                if form_is_fillable(parsed_fields):
                    detected_forms_dict[form_index] = (html, text, url)
                    print(f"[DEBUG] Added form {form_index} — fillable")
                    form_index += 1
                else:
                    print(
                        f"[SKIPPED] Form {form_index} skipped — not fillable")
        except:
            continue

    log['form_detected'] = len(detected_forms_dict) > 0
    log['form_page_urls'] = [url for _,
                             (_, _, url) in detected_forms_dict.items()]

    if not page_texts:
        page_texts = nested_subpage_recovery(driver, domain_url, log)

    driver.quit()

    if page_texts:
        combined_text = "\n\n".join(page_texts.values())

        # === TOGGLE BETWEEN METHODS HERE ===
        # Default: use manual NLP method
        email_method = 'NLP'
        extracted_emails = extract_emails_from_text(combined_text)

        # Optional: switch to GPT-based method by uncommenting:
        # email_method = 'gpt'
        # extracted_emails = extract_emails_using_gpt_combined(page_texts, log)

        log['email_extraction'] = {
            'method_used': email_method,
            'emails_found': extracted_emails,
        }

    else:
        log['timed_out'] = True

    log['token_usage']['estimated_cost_usd'] = round(
        (log['token_usage']['tokens_used'] / 1000) * GPT_COST_PER_1K_TOKENS, 5
    )

    chosen_form = process_detected_forms(log, detected_forms_dict)

    if chosen_form:
        log['chosen_form'] = chosen_form

    return log
