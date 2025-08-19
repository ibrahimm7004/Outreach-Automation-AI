from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from utils.text_utils import normalize_text
from config import INTENT_KEYWORDS, EXCLUSION_PHRASES


def is_relevant_link(text):
    text_clean = normalize_text(text)
    if any(ex in text_clean for ex in EXCLUSION_PHRASES):
        return False
    import spacy
    nlp = spacy.load("en_core_web_sm")  # Only load when needed
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
                href = a["href"]
                if not href or not text:
                    continue
                if not all_links:
                    if "about" in text.lower() and not text.lower().strip().startswith("about"):
                        continue
                links.append((text, href))
        except:
            continue

    print(f"Total links found: {len(links)}")
    return links
