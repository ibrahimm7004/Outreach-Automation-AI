import time
import re
import unicodedata
import spacy
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

nlp = spacy.load("en_core_web_sm")

CHROMEDRIVER_PATH = r"C:\\Users\\hp\\Desktop\\leadsup\\v0\\chromedriver-win64\\chromedriver.exe"
URLS_FILE_PATH = r"C:\\Users\\hp\\Desktop\\leadsup\\v0\\urls.txt"

INTENT_KEYWORDS = ["contact", "advertise", "ad",
                   "marketing", "sales", "press", "collaborate"]
EXCLUSION_PHRASES = ["terms of sale", "terms", "policy",
                     "markets", "media & entertainment", "media-entertainment"]


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
            print(
                "[WARN] Scrolling timeout exceeded. Attempting to proceed with partial content.")
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
    return list(set(standard + deobfuscated))


def nested_subpage_recovery(driver, domain_url):
    print("[INFO] Initiating fallback scan using all links on the main page...")
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
                print(f"[SKIP] No content found on {page_url}. Skipping.")
                continue
            emails = extract_emails_from_text(text)
            if emails:
                final_emails[page_url] = emails
        except:
            continue

    return final_emails


def process_domain(domain_url):
    options = Options()
    # options.add_argument("--headless")
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

    if found_links:
        print(f"[+] Relevant links found on {domain_url}:")
        for k, v in found_links.items():
            print(f" - {k}: '{k}' -> {v}")

    domain_emails = {}

    for page_name, page_url in found_links.items():
        try:
            driver.get(page_url)
            scroll_to_bottom(driver)
            text = extract_text_from_page(driver)
            if not text.strip():
                print(f"   [!] No content found on {page_url}. Skipping.")
                continue
            emails = extract_emails_from_text(text)
            valid_emails = [e for e in emails if e != "."]
            if valid_emails:
                domain_emails[page_name] = valid_emails
        except Exception as e:
            print(f"   [!] Error while processing {page_url}: {e}")

    if not any(domain_emails.values()):
        print(
            "[WARN] No emails found using initial strategy. Retrying with nested subpage scan...")
        domain_emails = nested_subpage_recovery(driver, domain_url)

    driver.quit()
    return domain_emails


def main():
    with open(URLS_FILE_PATH, "r") as file:
        urls = [line.strip() for line in file if line.strip()]

    final_data = {}
    for url in urls:
        try:
            email_dict = process_domain(url)
            final_data[url] = email_dict
        except Exception as e:
            print(f"[!] Error with domain {url}: {e}")

    print("\n===== FINAL EMAIL DICTIONARY =====")
    print(final_data)


if __name__ == "__main__":
    main()
