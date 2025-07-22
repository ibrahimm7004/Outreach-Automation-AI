import time
import re
import unicodedata
import spacy
import json
import os
import pandas as pd
import subprocess
import psutil
import warnings
import sys
import contextlib
from concurrent.futures import ThreadPoolExecutor, TimeoutError as ThreadTimeoutError
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from openai import OpenAI
from threading import Timer
from dotenv import load_dotenv

warnings.filterwarnings("ignore")

load_dotenv()
nlp = spacy.load("en_core_web_sm")

CHROMEDRIVER_PATH = r"C:\\Users\\hp\\Desktop\\leadsup\\v0\\chromedriver-win64\\chromedriver.exe"
CSV_FILE_PATH = r"C:\\Users\\hp\\Desktop\\leadsup\\v0\\lb_findings_domains_emails_forms.csv"
LOGS_DIR_PATH = r"C:\\Users\\hp\\Desktop\\leadsup\\v0\\logs"

INTENT_KEYWORDS = ["contact", "advertise", "ad",
                   "marketing", "sales", "press", "collaborate"]
EXCLUSION_PHRASES = ["terms of sale", "terms", "policy",
                     "markets", "media & entertainment", "media-entertainment"]

GPT_MAX_TOKENS = 16000
SAFETY_BUFFER_TOKENS = 1000
AVAILABLE_TEXT_TOKENS = GPT_MAX_TOKENS - SAFETY_BUFFER_TOKENS
GPT_COST_PER_1K_TOKENS = 0.005

key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=key)


def monitor_and_kill_outlook():
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] and 'outlook' in proc.info['name'].lower():
            print("[WARNING] Outlook detected — killing process.")
            proc.kill()


def print_debug(message):
    print(f"\n{'='*30}\n[DEBUG] {message}\n")


def normalize_text(text):
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s@\[\]\(\)\.-]+", "", text)
    return text.strip().lower()


def is_relevant_link(text):
    text_clean = normalize_text(text)
    if any(ex in text_clean for ex in EXCLUSION_PHRASES):
        return False
    doc = nlp(text_clean)
    lemmas = {token.lemma_ for token in doc}
    relevant_links = any(k in lemmas for k in INTENT_KEYWORDS)
    return relevant_links


def extract_links(driver, restrict_to_header_footer=True, all_links=False):
    print("Extracting links from page...")
    links = []
    sections = []
    if restrict_to_header_footer:
        for tag in ["header", "footer"]:
            try:
                sections.append(driver.find_element(By.TAG_NAME, tag))
            except:
                continue
    else:
        sections = [driver.find_element(By.TAG_NAME, "body")]

    for section in sections:
        try:
            soup = BeautifulSoup(section.get_attribute(
                "innerHTML"), "html.parser")
            for a in soup.find_all("a", href=True):
                text = a.get_text(strip=True)
                href = a['href']
                if not href or not text:
                    continue
                if not all_links:
                    if 'about' in text.lower() and not text.lower().strip().startswith('about'):
                        continue
                    links.append((text, href))
                else:
                    links.append((text, href))
        except:
            continue

    print(f"Total links found: {len(links)}")

    return links


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


def extract_text_from_page(driver):
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        html = body.get_attribute("innerHTML")
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator="\n")
    except:
        return ""


def detect_forms_in_html(html, page_text, log, page_url):
    global detected_forms_dict
    try:
        soup = BeautifulSoup(html, "html.parser")
        forms = soup.find_all("form")
        for i, form in enumerate(forms):
            form_snippet = str(form)[:1000]
            if evaluate_form_relevance_with_gpt(form_snippet, page_text, log):
                index = len(detected_forms_dict) + 1
                detected_forms_dict[index] = form_snippet + "\n\n" + page_text
                print(f"[FORM DETECTED] Page URL: {page_url}")
    except Exception as e:
        print(f"[ERROR] Error while detecting forms: {e}")


def evaluate_form_relevance_with_gpt(form_html, page_text, log):
    try:
        total_chars = len(form_html) + len(page_text)
        if total_chars > AVAILABLE_TEXT_TOKENS:
            page_text = summarize_page_text(page_text, log)

        prompt = f"""Evaluate the following HTML form snippet and the surrounding page content.
Is this a relevant contact form for advertising, marketing, or press inquiries?
Respond ONLY with True or False.

Form HTML:
{form_html}

Page Text:
{page_text}"""

        response = client.responses.create(
            model="gpt-4o-mini",
            input=[{"role": "user", "content": prompt}]
        )
        reply = response.output_text.strip().lower()
        return reply == "true"

    except Exception as e:
        print(f"[API ERROR] Failed to evaluate form relevance: {e}")
        return False


def extract_text_and_detect_form(driver, log, page_url):
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        html = body.get_attribute("innerHTML")
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n")
        detect_forms_in_html(html, text, log, page_url)
        return text
    except:
        return ""


def summarize_form_text_for_selection(content, log):
    prompt = f"""Summarize the purpose of the following webpage HTML form and page content in one sentence. 
Indicate what the form is about and what kind of contact it's intended for:

{content}"""
    try:
        token_est = len(prompt.split())
        log['token_usage']['tokens_used'] += token_est
        response = client.responses.create(
            model="gpt-4o-mini",
            input=[{"role": "user", "content": prompt}]
        )
        return response.output_text.strip()
    except Exception as e:
        print(f"[API ERROR] Failed to summarize form content: {e}")
        return ""


def choose_best_form_using_gpt(summary_dict, log):
    prompt = """Given the following numbered summaries of different contact forms found across a website, choose the ONE most relevant for advertising, marketing, or press inquiries. Only return the number of the most appropriate summary. 
If multiple seem equally relevant, choose the one with the clearest purpose.

"""
    for key, summary in summary_dict.items():
        prompt += f"{key}: {summary}\n"
    prompt += "\nReturn only the number (e.g., 2)."

    try:
        token_est = len(prompt.split())
        log['token_usage']['tokens_used'] += token_est
        response = client.responses.create(
            model="gpt-4o-mini",
            input=[{"role": "user", "content": prompt}]
        )
        result = response.output_text.strip()
        return int(result) if result.isdigit() else None
    except Exception as e:
        print(f"[API ERROR] Failed to select best form: {e}")
        return None


def process_detected_forms(log):
    global detected_forms_dict
    if len(detected_forms_dict) == 0:
        return None
    elif len(detected_forms_dict) == 1:
        return list(detected_forms_dict.values())[0]  # only one form
    else:
        print("\n[INFO] Multiple forms detected. Building summaries...")
        summarized_dict = {}
        for idx, content in detected_forms_dict.items():
            summarized = summarize_form_text_for_selection(content, log)
            summarized_dict[idx] = summarized

        print("\n[DEBUG] Form Summaries:", summarized_dict)
        print("\n[DEBUG] Full Form Content:", detected_forms_dict)

        chosen_key = choose_best_form_using_gpt(summarized_dict, log)
        if chosen_key and chosen_key in detected_forms_dict:
            return detected_forms_dict[chosen_key]
    return None


def extract_emails_from_text(text):
    print("\nExtracting emails from text...")
    text = normalize_text(text)
    obfuscated = re.findall(
        r"[\w\.-]+\s?\[?at\]?\s?[\w\.-]+\s?(dot|\.)\s?[a-z]{2,}", text)
    deobfuscated = [re.sub(
        r"\s?\[?at\]?\s?", "@", re.sub(r"\s?(dot|\.)\s?", ".", m)) for m in obfuscated]
    standard = re.findall(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}", text)
    all_emails = list(set(standard + deobfuscated))
    final_emails = [email for email in all_emails if email != "."]
    print(f"Emails found: {final_emails}")
    return final_emails


def summarize_page_text(text, log):
    prompt = (
        "Summarize the following webpage content and extract only the email addresses and their contexts relevant to marketing, advertising or press.\n\n"
        f"{text[:3000]}"
    )
    try:
        token_est = len(prompt.split())
        log['token_usage']['summarize_calls'] += 1
        log['token_usage']['tokens_used'] += token_est
        response = client.responses.create(
            model="gpt-4o-mini", input=[{"role": "user", "content": prompt}])
        print("\nGPT summarization response:\n" +
              response.output_text.strip())
        return client.responses.create(model="gpt-4o-mini", input=[{"role": "user", "content": prompt}]).output_text.strip()
    except Exception as e:
        print(f"[API ERROR] Failed to summarize page: {e}")
        return ""


def extract_emails_using_gpt_combined(pages_dict, log):
    print("\nCombining texts from multiple pages for GPT email extraction")
    combined_parts = []
    total_chars = sum(len(v) for v in pages_dict.values())

    if total_chars < AVAILABLE_TEXT_TOKENS:
        for name, text in pages_dict.items():
            combined_parts.append(f"### Page: {name}\n{text}")
    else:
        avg_limit = AVAILABLE_TEXT_TOKENS // len(pages_dict)
        for name, text in pages_dict.items():
            if len(text) > avg_limit:
                text = summarize_page_text(text, log)
            combined_parts.append(f"### Page: {name}\n{text}")

    combined_text = "\n\n".join(combined_parts)
    prompt = (
        "You are helping a marketing agency find the most appropriate email addresses for advertising, marketing partnerships, or press inquiries.\n"
        "Below are page contents from a website. Return the best 1–3 emails based on relevance. If you find no clear match, return the most relevant one you can find.\n"
        "Do NOT return anything outside of a plain comma-separated list of email addresses.\n"
        "Return an empty string ONLY if absolutely no email addresses are found.\n\n"
        f"{combined_text[:AVAILABLE_TEXT_TOKENS]}"
    )
    try:
        token_est = len(prompt.split())
        log['token_usage']['tokens_used'] += token_est
        response = client.responses.create(
            model="gpt-4o-mini", input=[{"role": "user", "content": prompt}])
        print("\nGPT email extraction response:\n" +
              response.output_text.strip())
        return [e.strip() for e in response.output_text.split(",") if e.strip() and re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+", e.strip())]
    except Exception as e:
        print(f"[API ERROR] Failed to extract emails: {e}")
        return []


def nested_subpage_recovery(driver, domain_url, log):
    print("\nPerforming nested subpage recovery")
    log['used_recovery'] = True
    all_links = extract_links(
        driver, restrict_to_header_footer=False, all_links=True)
    seen_urls = set()
    final_emails = {}
    page_urls = [urljoin(domain_url, href) for _, href in all_links if href]

    for page_url in page_urls:
        if page_url in seen_urls:
            continue
        seen_urls.add(page_url)
        try:
            driver.get(page_url)
            scroll_to_bottom(driver)
            text = extract_text_from_page(driver)
            if not text.strip():
                continue
            emails = extract_emails_from_text(text)
            if emails:
                final_emails[page_url] = emails
        except:
            continue

    print(f"\nSubpage emails found: {final_emails}")
    return final_emails


@contextlib.contextmanager
def suppress_output():
    with open(os.devnull, "w") as fnull:
        with contextlib.redirect_stdout(fnull), contextlib.redirect_stderr(fnull):
            yield


def process_domain(domain_url, expected_email):
    log = {
        'domain': domain_url,
        'manual_emails': [],
        'gpt_emails': [],
        'token_usage': {'tokens_used': 0, 'summarize_calls': 0},
        'matches_expected': {'manual': False, 'gpt': False},
        'used_recovery': False,
        'timed_out': False,
        'form_detected': False
    }

    start_time = time.time()
    options = Options()
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

    # Main crawl loop limited only to initially found relevant links
    page_texts = {}
    for page_name, page_url in found_links.items():
        if time.time() - start_time > 240:
            log['timed_out'] = True
            print(f"[TIME LIMIT] Partial scrape used for {domain_url}.")
            break
        try:
            driver.get(page_url)
            scroll_to_bottom(driver)
            text = extract_text_from_page(driver)
            if text.strip():
                page_texts[page_name] = text
        except:
            continue

    if not page_texts:
        page_texts = nested_subpage_recovery(driver, domain_url, log)

    driver.quit()

    if page_texts:
        combined_text = "\n\n".join(page_texts.values())
        log['manual_emails'] = extract_emails_from_text(combined_text)
        log['gpt_emails'] = extract_emails_using_gpt_combined(page_texts, log)
        log['matches_expected']['manual'] = expected_email.lower() in [e.lower()
                                                                       for e in log['manual_emails']]
        log['matches_expected']['gpt'] = expected_email.lower() in [e.lower()
                                                                    for e in log['gpt_emails']]
    else:
        log['timed_out'] = True

    log['token_usage']['estimated_cost_usd'] = round(
        (log['token_usage']['tokens_used'] / 1000) * GPT_COST_PER_1K_TOKENS, 5)
    return log


def main():
    print_debug("Starting scraping process")

    df = pd.read_csv(CSV_FILE_PATH)
    df = df.dropna(subset=['domain'])

    for _, row in df.iterrows():
        domain = row['domain'].strip()
        expected_email = str(
            row['email/form']).strip() if pd.notna(row['email/form']) else ""
        expected_form = 'form' in expected_email.lower()

        print_debug(f"Processing domain: {domain}")

        monitor_and_kill_outlook()

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    process_domain, "https://" + domain, expected_email)
                log = future.result(timeout=300)
        except ThreadTimeoutError:
            log = {
                'domain': domain,
                'manual_emails': [],
                'gpt_emails': [],
                'token_usage': {'tokens_used': 0, 'summarize_calls': 0, 'estimated_cost_usd': 0},
                'matches_expected': {'manual': False, 'gpt': False, 'form': False},
                'used_recovery': False,
                'timed_out': True,
                'form_detected': False
            }
            print_debug(f"[TIMEOUT] Skipped {domain} after full limit.")
        except Exception as e:
            print_debug(f"[ERROR] Failed to process {domain}: {e}")
            continue

        log['matches_expected']['form'] = log['form_detected'] and expected_form

        with open(os.path.join(LOGS_DIR_PATH, f"{domain.replace('.', '_')}.json"), 'w', encoding='utf-8') as f:
            json.dump(log, f, indent=2)
            print_debug(f"{domain} completed and log saved.")

    print_debug("Scraping completed for all domains")


if __name__ == "__main__":
    main()
