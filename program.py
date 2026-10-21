import time
import json
from json import JSONDecodeError
from selenium import webdriver
from pathlib import Path
from bs4 import BeautifulSoup
import PySimpleGUI as sg
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from words import WordDb

path = Path("data.json")
default_data = {
    "user-data": "C:\\Users\\tcasa\\selenium-chrome-data",
    "profile-name": "Default",
    "gimkit-link": "https://gimkit.com"
}

ANSWER_SELECTOR = "div.sc-ixcdjX.kLONFv"
CONTINUE_SELECTOR = "div.sc-eEHciv.hkdshG"


LISTENER_JS = """
if (!window.__listenerInstalled) {
    window.__listenerInstalled = true;
    window.__clicked = [];
    document.addEventListener('click', e => {
        const el = e.target.closest('.sc-ixcdjX.kLONFv');
        if (!el) return;
        const span = el.querySelector('span.notranslate');
        const word = document.querySelector('.sc-itBLYH.botDlG span.lang-en');
        window.__clicked.push({
            answer: (span || el).innerText.trim(),
            word: word ? word.textContent.trim() : null,
        });
    }, true);
}
"""

POP_CLICKS_JS = "const c = window.__clicked || []; window.__clicked = []; return c;"


def loadSettings():
    data = default_data
    print("loading json")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print("File not found, creating file")
        with path.open("w", encoding="utf-8") as f:
            json.dump(default_data, f, indent=4)
            print("File created")
        return default_data
    except JSONDecodeError:
        print("Json decode error")
        return default_data
    else:
        print("Loaded successfully")
        return data

    return data

def makeChromeDriver(data) -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument(f"--user-data-dir={data["user-data"]}")
    options.add_argument(f"--profile-directory={data["profile-name"]}")
    options.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=options, keep_alive=True)
    return driver

def readLatinText(driver: webdriver.Chrome) -> str | None:
    soup = BeautifulSoup(driver.page_source, "html.parser")
    span = soup.select_one(".sc-itBLYH.botDlG span.lang-en")
    return span.get_text(strip=True) if span else None

def normalize(text: str) -> str:
    return " ".join(text.split()).lower()

def renderWindow() -> sg.Window:
    layout = [
        [
            sg.Text("Current Latin Word: None", key="-LATINWORD-"),
            sg.Text("Last pressed def: None", key="-ENGWORD-"),
        ],
        [
            sg.Text("Table: None", key="-DEF-"),
        ],
        [
            sg.Text("Start assignment, open vocab quiz and press start")
        ],
        [
            sg.Button("Start")
        ]
    ]

    window = sg.Window(title="Auto gimkit", layout=layout, margins=[15, 15], keep_on_top=True, finalize=True)
    return window

def setReadLatinOnWindow(window: sg.Window, txt: str | None, color = "white"):
    window["-LATINWORD-"].update(f"Current Latin Word: {txt}", text_color=color)

def setDefOnWindow(window: sg.Window, txt: str, color="white"):
    window["-ENGWORD-"].update(f"Last pressed def: {txt}", text_color=color)

def setFoundOnWindow(window: sg.Window, txt: str, color="white"):
    window["-DEF-"].update(f"Table: {txt}", text_color=color)


def injectClickListener(driver: webdriver.Chrome) -> None:
    driver.execute_script(LISTENER_JS)

def popClicks(driver: webdriver.Chrome) -> list[dict]:
    return driver.execute_script(POP_CLICKS_JS)

def clearClicks(driver: webdriver.Chrome) -> None:
    driver.execute_script("window.__clicked = [];")

def getAnswerElement(driver, text: str, exact=True):
    target = text.strip().lower()
    for div in driver.find_elements(By.CSS_SELECTOR, ANSWER_SELECTOR):
        for span in div.find_elements(By.CSS_SELECTOR, "span.notranslate"):
            content = span.text.strip().lower()
            if (content == target) if exact else (target in content):
                return div
    return None

def clickAnswer(driver, text: str, exact=True, retries=3) -> bool:
    for _ in range(retries):
        try:
            div = getAnswerElement(driver, text, exact)
            if div is None:
                return False
            div.click()
            return True
        except (StaleElementReferenceException, ElementClickInterceptedException):
            time.sleep(0.02)
    return False

def clickContinue(driver, timeout=3, retries=3) -> bool:
    locator = (By.CSS_SELECTOR, CONTINUE_SELECTOR)
    for _ in range(retries):
        try:
            WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable(locator)
            ).click()
            return True
        except (StaleElementReferenceException, ElementClickInterceptedException):
            time.sleep(0.02)
        except TimeoutException:
            return False
    return False


def main():
    data = loadSettings()
    words = WordDb()
    window = renderWindow()
    driver = makeChromeDriver(data)
    driver.get(data["gimkit-link"])

    checkInterval = 75
    started = False
    handledWord = None
    lastPrinted = None

    try:
        while True:
            event, _ = window.read(timeout=checkInterval)
            if event == sg.WIN_CLOSED:
                break
            if event == "Start":
                started = True

            try:
                injectClickListener(driver)
                latinText = readLatinText(driver)
                clicked = popClicks(driver)
            except WebDriverException:
                print("Browser was closed")
                break

            if latinText != lastPrinted:
                print("Latin word:", latinText)
                lastPrinted = latinText

            if not started:
                continue

            for item in clicked:
                answer = item.get("answer")
                word = item.get("word")
                print("Clicked:", answer, "for", word)

                if answer:
                    pass
                    # setDefOnWindow(window, answer, "orange")
                if answer and word:
                    print("Saved:", words.add(word, answer))
                    handledWord = normalize(word)

            if latinText is None:
                handledWord = None
                setReadLatinOnWindow(window, "None", "red")
                continue

            # setReadLatinOnWindow(window, latinText, "green")

            entry = words.get(latinText)
            if entry is None:
                # setFoundOnWindow(window, "PLEASE SELECT ANSWER")
                continue

            answer = entry["english"]
            setFoundOnWindow(window, answer)

            if normalize(latinText) == handledWord:
                continue

            if clickAnswer(driver, answer):
                handledWord = normalize(latinText)
                clickContinue(driver)
                clearClicks(driver)
    finally:
        words.flush()
        window.close()
        try:
            driver.quit()
        except WebDriverException:
            pass
        print("PROGRAM ENDED")

if __name__ == "__main__":
    main()