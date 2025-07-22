import time
import re
import unicodedata
import spacy
import json
import os
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, TimeoutError as ThreadTimeoutError
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from openai import OpenAI

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

client = OpenAI(api_key=key)


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
    return any(k in lemmas for k in INTENT_KEYWORDS)


def extract_links(driver, restrict_to_header_footer=True, all_links=False):
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


def extract_emails_from_text(text):
    text = normalize_text(text)
    obfuscated = re.findall(
        r"[\w\.-]+\s?\[?at\]?\s?[\w\.-]+\s?(dot|\.)\s?[a-z]{2,}", text)
    deobfuscated = [re.sub(
        r"\s?\[?at\]?\s?", "@", re.sub(r"\s?(dot|\.)\s?", ".", m)) for m in obfuscated]
    standard = re.findall(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}", text)
    all_emails = list(set(standard + deobfuscated))
    return [email for email in all_emails if email != "."]


def summarize_page_text(text, log):
    prompt = (
        "Summarize the following webpage content and extract only the email addresses and their contexts relevant to marketing, advertising or press.\n\n"
        f"{text[:3000]}"
    )
    try:
        token_est = len(prompt.split())
        log['token_usage']['summarize_calls'] += 1
        log['token_usage']['tokens_used'] += token_est
        return client.responses.create(model="gpt-4o-mini", input=[{"role": "user", "content": prompt}]).output_text.strip()
    except Exception as e:
        print(f"[API ERROR] Failed to summarize page: {e}")
        return ""


def extract_emails_using_gpt_combined(pages_dict, log):
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
        return [e.strip() for e in response.output_text.split(",") if e.strip() and re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+", e.strip())]
    except Exception as e:
        print(f"[API ERROR] Failed to extract emails: {e}")
        return []


def nested_subpage_recovery(driver, domain_url, log):
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

    return final_emails


def process_domain(domain_url, expected_email):
    log = {
        'domain': domain_url,
        'manual_emails': [],
        'gpt_emails': [],
        'token_usage': {'tokens_used': 0, 'summarize_calls': 0},
        'matches_expected': {'manual': False, 'gpt': False},
        'used_recovery': False,
        'timed_out': False
    }

    start_time = time.time()
    options = Options()
    options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(service=Service(
        CHROMEDRIVER_PATH), options=options)
    driver.get(domain_url)
    time.sleep(3)

    raw_links = extract_links(driver, restrict_to_header_footer=True)
    found_links = {}
    seen_urls = set()

    for text, href in raw_links:
        abs_url = urljoin(domain_url, href)
        if abs_url in seen_urls:
            continue
        if is_relevant_link(text):
            found_links[text] = abs_url
            seen_urls.add(abs_url)

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
    df = pd.read_csv(CSV_FILE_PATH)

    processed_domains = set()
    for fname in os.listdir(LOGS_DIR_PATH):
        if fname.endswith(".json"):
            with open(os.path.join(LOGS_DIR_PATH, fname), 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                    processed = data.get("domain", "").replace(
                        "https://", "").replace("http://", "").strip("/")
                    if processed:
                        processed_domains.add(processed)
                except:
                    continue

    for _, row in df.iterrows():
        domain = row['domain'].strip().replace(
            "https://", "").replace("http://", "").strip("/")
        expected_email = str(
            row['email/form']) if pd.notna(row['email/form']) else ''

        if domain in processed_domains:
            print(f"[SKIP] Already processed {domain}")
            continue

        print(f"[INFO] Processing {domain}...")

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
                'matches_expected': {'manual': False, 'gpt': False},
                'used_recovery': False,
                'timed_out': True
            }
            print(f"[TIMEOUT] Skipped {domain} after full limit.")
        except Exception as e:
            print(f"[ERROR] Failed to process {domain}: {e}")
            continue

        with open(os.path.join(LOGS_DIR_PATH, f"{domain.replace('.', '_')}.json"), 'w', encoding='utf-8') as f:
            json.dump(log, f, indent=2)


if __name__ == "__main__":
    main()
