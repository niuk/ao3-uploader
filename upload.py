"""
AO3 Chapter Uploader

Automates uploading chapters from a NovelCrafter HTML export to Archive of Our Own.

Usage:
    python upload.py <html_file> --work-id <work_id>
    python upload.py <html_file> --work-id <work_id> --dry-run

The HTML file should be a NovelCrafter export containing chapter headings (h1/h2)
that divide the content into chapters.
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_chapters(html_path: Path) -> list[dict]:
    """
    Parse a NovelCrafter HTML export and split it into chapters.
    
    Each chapter dict contains:
        - title: str (the heading text)
        - content: str (the inner HTML of that chapter's body)
    """
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "lxml")

    chapters: list[dict] = []
    
    # NovelCrafter typically uses h1 or h2 for chapter titles
    # We'll look for heading elements and collect content until the next heading
    headings = soup.find_all(re.compile(r"^h[12]$", re.I))
    
    if not headings:
        # Fallback: treat entire document as one chapter
        body = soup.find("body") or soup
        return [{
            "title": "Chapter 1",
            "content": "".join(str(child) for child in body.children)
        }]
    
    for i, heading in enumerate(headings):
        title = heading.get_text(strip=True)
        
        # Collect all siblings until the next heading (or end)
        content_parts = []
        for sibling in heading.find_next_siblings():
            if sibling.name and re.match(r"^h[12]$", sibling.name, re.I):
                break
            content_parts.append(str(sibling))
        
        chapters.append({
            "title": title,
            "content": "\n".join(content_parts)
        })
    
    return chapters


# ---------------------------------------------------------------------------
# Selenium helpers
# ---------------------------------------------------------------------------

def create_driver(headless: bool = False) -> webdriver.Chrome:
    """Create and return a Chrome WebDriver."""
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    # Keep browser open after script ends for debugging
    options.add_experimental_option("detach", True)
    return webdriver.Chrome(options=options)


def wait_for(driver, by, value, timeout: int = 10):
    """Wait for an element to be present and return it."""
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, value))
    )


def wait_clickable(driver, by, value, timeout: int = 10):
    """Wait for an element to be clickable and return it."""
    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, value))
    )


def safe_send_keys(driver, element, text: str):
    """Send keys to an element, falling back to JavaScript if needed."""
    try:
        element.clear()
        element.send_keys(text)
    except Exception:
        # Fallback: use JavaScript to set the value
        driver.execute_script("arguments[0].value = arguments[1];", element, text)


# ---------------------------------------------------------------------------
# AO3 automation
# ---------------------------------------------------------------------------

def login(driver, username: str, password: str):
    """Log in to AO3."""
    print("Navigating to AO3 login page...")
    driver.get("https://archiveofourown.org/users/login")
    
    # Wait for page to fully load
    time.sleep(2)
    
    # Wait for the form to be present
    user_field = wait_for(driver, By.ID, "user_login", timeout=15)
    safe_send_keys(driver, user_field, username)
    
    pass_field = driver.find_element(By.ID, "user_password")
    safe_send_keys(driver, pass_field, password)
    
    # Click the submit button using JavaScript as fallback
    submit = driver.find_element(By.NAME, "commit")
    try:
        submit.click()
    except Exception:
        driver.execute_script("arguments[0].click();", submit)
    
    # Wait for redirect / dashboard
    try:
        wait_for(driver, By.CSS_SELECTOR, "ul.user.navigation", timeout=15)
        print("Login successful!")
    except TimeoutException:
        # Check for error message
        if "Invalid Username or password" in driver.page_source:
            raise RuntimeError("Login failed: invalid credentials")
        raise RuntimeError("Login failed: unexpected page state")


def navigate_to_add_chapter(driver, work_id: str):
    """Navigate to the 'Add Chapter' page for a given work."""
    url = f"https://archiveofourown.org/works/{work_id}/chapters/new"
    print(f"Navigating to add chapter: {url}")
    driver.get(url)
    
    # Wait for the chapter form to load
    wait_for(driver, By.ID, "chapter_content", timeout=15)


def upload_chapter(driver, work_id: str, title: str, content: str, dry_run: bool = False):
    """
    Upload a single chapter to an existing AO3 work.
    
    Args:
        driver: Selenium WebDriver
        work_id: The numeric ID of the AO3 work
        title: Chapter title
        content: Chapter content (HTML)
        dry_run: If True, fill the form but don't submit
    """
    navigate_to_add_chapter(driver, work_id)
    
    # Fill in chapter title
    title_field = driver.find_element(By.ID, "chapter_title")
    title_field.clear()
    title_field.send_keys(title)
    
    # Fill in chapter content
    # AO3 uses a textarea; we inject HTML directly
    content_field = driver.find_element(By.ID, "chapter_content")
    content_field.clear()
    content_field.send_keys(content)
    
    if dry_run:
        print(f"  [DRY RUN] Would submit chapter: {title}")
        return
    
    # Click the "Post" button
    post_btn = driver.find_element(By.CSS_SELECTOR, "input[name='commit'][value='Post']")
    post_btn.click()
    
    # Wait for confirmation (redirect to chapter view)
    try:
        wait_for(driver, By.CSS_SELECTOR, "div.chapter", timeout=20)
        print(f"  ✓ Posted: {title}")
    except TimeoutException:
        print(f"  ✗ Failed to confirm post for: {title}")


def upload_all_chapters(
    driver,
    work_id: str,
    chapters: list[dict],
    start_index: int = 0,
    dry_run: bool = False,
):
    """
    Upload multiple chapters to an AO3 work.
    
    Args:
        driver: Selenium WebDriver
        work_id: The numeric ID of the AO3 work
        chapters: List of chapter dicts with 'title' and 'content'
        start_index: Skip chapters before this index (0-based)
        dry_run: If True, fill forms but don't submit
    """
    total = len(chapters)
    for i, chapter in enumerate(chapters):
        if i < start_index:
            print(f"Skipping chapter {i+1}/{total}: {chapter['title']}")
            continue
        
        print(f"Uploading chapter {i+1}/{total}: {chapter['title']}")
        upload_chapter(driver, work_id, chapter["title"], chapter["content"], dry_run)
        
        # Be polite to AO3's servers
        if not dry_run and i < total - 1:
            time.sleep(3)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    load_dotenv()
    
    parser = argparse.ArgumentParser(
        description="Upload chapters from a NovelCrafter HTML export to AO3."
    )
    parser.add_argument("html_file", type=Path, help="Path to the exported HTML file")
    parser.add_argument("--work-id", required=True, help="AO3 work ID to add chapters to")
    parser.add_argument("--start", type=int, default=0, help="Chapter index to start from (0-based)")
    parser.add_argument("--dry-run", action="store_true", help="Parse and fill forms, but don't submit")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--list-chapters", action="store_true", help="Just list parsed chapters and exit")
    args = parser.parse_args()
    
    # Validate HTML file
    if not args.html_file.exists():
        print(f"Error: file not found: {args.html_file}", file=sys.stderr)
        sys.exit(1)
    
    # Parse chapters
    print(f"Parsing {args.html_file}...")
    chapters = parse_chapters(args.html_file)
    print(f"Found {len(chapters)} chapter(s).")
    
    if args.list_chapters:
        for i, ch in enumerate(chapters):
            preview = ch["content"][:80].replace("\n", " ") + "..."
            print(f"  {i+1}. {ch['title']}: {preview}")
        sys.exit(0)
    
    # Credentials from environment
    username = os.getenv("AO3_USERNAME")
    password = os.getenv("AO3_PASSWORD")
    if not username or not password:
        print("Error: AO3_USERNAME and AO3_PASSWORD must be set in .env", file=sys.stderr)
        sys.exit(1)
    
    # Launch browser and upload
    driver = create_driver(headless=args.headless)
    try:
        login(driver, username, password)
        upload_all_chapters(driver, args.work_id, chapters, args.start, args.dry_run)
        print("Done!")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if args.headless:
            driver.quit()
        else:
            print("Browser left open for inspection. Close it manually when done.")


if __name__ == "__main__":
    main()
