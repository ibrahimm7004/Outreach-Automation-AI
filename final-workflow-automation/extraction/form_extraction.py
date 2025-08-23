from bs4 import BeautifulSoup, Tag
from gpt.evaluators import evaluate_form_relevance_with_gpt


def extract_form_details_from_driver(driver, page_num, page_url, log):
    result = {}
    try:
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, "html.parser")
        forms = soup.find_all("form")

        if not forms:
            print("[NOT FOUND] No form found on page")
            return result

        for idx, form in enumerate(forms):
            input_tags = form.find_all(["input", "textarea", "select"])

            if len(input_tags) == 1:
                input_type = input_tags[0].get("type", "text").lower()
                input_name = input_tags[0].get("name", "").lower()
                if input_type == "search" or input_name == "s":
                    print(
                        f"[SKIPPED] Search form filtered out. URL: {page_url}")
                    continue

            has_textarea = any(tag.name == "textarea" for tag in input_tags)
            has_other_field = any(tag.name != "textarea" for tag in input_tags)

            if not (has_textarea and has_other_field):
                print(
                    f"[SKIPPED] Form lacks message box + 1 other input. URL: {page_url}")
                continue

            form_html = str(form)
            important_text = []

            title_tag = soup.find("title")
            if title_tag and title_tag.text.strip():
                important_text.append(f"Page Title: {title_tag.text.strip()}")

            parent = form.parent
            for _ in range(3):
                if not parent:
                    break
                nearby_text = parent.get_text(separator=" ", strip=True)
                if nearby_text:
                    important_text.append(nearby_text)
                parent = parent.parent

            form_text = form.get_text(separator=" ", strip=True)
            if form_text:
                important_text.append(f"Form Content: {form_text}")

            final_text = "\n".join(important_text)

            is_relevant = evaluate_form_relevance_with_gpt(
                form_html, final_text, log)
            if is_relevant:
                result[page_num + idx] = [form_html, final_text, page_url]
                print(f"[RELEVANT FORM] Saved form {idx+1} from {page_url}")
            else:
                print(f"[SKIPPED] Form {idx+1} not relevant. URL: {page_url}")
    except Exception as e:
        print(f"[ERROR] Form detection failed: {e}")
    return result


def parse_form_fields(form_html):
    soup = BeautifulSoup(form_html, "html.parser")
    parsed_fields = []

    labels = {
        label.get("for"): label.get_text(strip=True)
        for label in soup.find_all("label")
        if label.get("for")
    }

    input_tags = soup.find_all(["input", "textarea", "select"])

    for tag in input_tags:
        if not isinstance(tag, Tag):
            continue

        field_info = {
            "tag": tag.name,
            "type": tag.get("type", "text").lower() if tag.name == "input" else tag.name,
            "name": tag.get("name") or tag.get("id") or "",
            "id": tag.get("id", ""),
            "required": bool(tag.has_attr("required") or tag.get("aria-required") == "true"),
            "placeholder": tag.get("placeholder") or "",
            "autocomplete": tag.get("autocomplete") or "",
            "maxlength": tag.get("maxlength") or "",
            "pattern": tag.get("pattern") or "",
            "class": tag.get("class", []),
            "style": tag.get("style", ""),
        }

        label_text = ""
        if field_info["id"] and field_info["id"] in labels:
            label_text = labels[field_info["id"]]
        elif tag.find_parent("label"):
            label_text = tag.find_parent("label").get_text(strip=True)
        elif tag.get("aria-label"):
            label_text = tag.get("aria-label")
        elif tag.get("placeholder"):
            label_text = tag.get("placeholder")
        else:
            prev_tag = tag.find_previous(["label", "div", "span"])
            if prev_tag and (txt := prev_tag.get_text(strip=True)) and len(txt) < 120:
                label_text = txt
            elif prev := tag.find_previous(string=True):
                cleaned = prev.strip()
                if 0 < len(cleaned) < 120:
                    label_text = cleaned

        if "*" in label_text and not field_info["required"]:
            field_info["required"] = True

        field_info["label"] = label_text.strip()

        if field_info["name"] or field_info["label"]:
            parsed_fields.append(field_info)

    return parsed_fields


def extract_submit_button(form_html):
    soup = BeautifulSoup(form_html, "html.parser")

    for button in soup.find_all("button"):
        if button.get("type", "submit").lower() == "submit" and not _is_hidden(button):
            return str(button)

    for inp in soup.find_all("input"):
        if inp.get("type", "").lower() in ["submit", "image"] and not _is_hidden(inp):
            return str(inp)

    for tag in soup.find_all(["div", "span"]):
        if tag.get("role") == "button" and not _is_hidden(tag):
            return str(tag)

    return None


def _is_hidden(tag):
    style = tag.get("style", "").lower()
    hidden_type = tag.get("type", "").lower() == "hidden"
    display_none = "display:none" in style.replace(" ", "")
    return hidden_type or display_none
