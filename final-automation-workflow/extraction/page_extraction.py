from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from urllib.parse import urljoin
from extraction.form_extraction import extract_form_details_from_driver
from extraction.link_extraction import extract_links
from utils.browser_utils import scroll_to_bottom
from utils.text_utils import extract_emails_from_text


def extract_text_from_page(driver, page_num, page_url, log):
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        html = body.get_attribute("innerHTML")
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n")
        form_dict = extract_form_details_from_driver(
            driver, page_num, page_url, log)
        return text, form_dict
    except:
        return "", {}


def nested_subpage_recovery(driver, domain_url, log):
    print("\nPerforming nested subpage recovery")
    log["used_recovery"] = True

    all_links = extract_links(
        driver, restrict_to_header_footer=False, all_links=True)
    seen_urls = set()
    final_emails = {}
    form_dict = {}

    page_urls = [urljoin(domain_url, href) for _, href in all_links if href]

    for i, page_url in enumerate(page_urls):
        if page_url in seen_urls:
            continue
        seen_urls.add(page_url)

        try:
            driver.get(page_url)
            scroll_to_bottom(driver)
            text, extracted_forms = extract_text_from_page(
                driver, i + 1, page_url, log)
            if not text.strip():
                continue
            emails = extract_emails_from_text(text)
            if emails:
                final_emails[page_url] = emails
            form_dict.update(extracted_forms)
        except Exception as e:
            print(f"[ERROR] during recovery at {page_url}: {e}")
            continue

    print("\n[RECOVERY FORM DICT RESULT]:")
    for idx, (html, context_text, url) in form_dict.items():
        print(
            f"\n[FORM {idx}] URL: {url}\nHTML (truncated): {html[:300]}...\nText: {context_text[:300]}...\n")

    print(f"\nSubpage emails found: {final_emails}")
    return final_emails
