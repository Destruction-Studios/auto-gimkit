import time
import pyautogui
import pytesseract
import difflib
import tkinter as tk
import ctypes
import json
import sys
from pathlib import Path
from PIL import ImageOps
from pynput import mouse

MATCH_THRESHOLD = 0.6
ORANGE, GREEN, RED = "#e08a00", "#2e9e5b", "#c0392b"

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

class Toast:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.label = tk.Label(self.root, font=("Segoe UI", 14, "bold"),
                              fg="white", padx=20, pady=12)
        self.label.pack()
        self.root.withdraw()
        self._hide_id = None

    def show(self, text, color="#2e9e5b", ms=2000):
        self.label.config(text=text, bg=color)
        self.root.update_idletasks()
        w = self.root.winfo_reqwidth()
        self.root.geometry(f"+{self.root.winfo_screenwidth() - w - 20}+20")
        self.root.deiconify()
        if self._hide_id:
            self.root.after_cancel(self._hide_id) 
        self._hide_id = self.root.after(ms, self.root.withdraw)
        self.root.update()

    def tick(self):
        self.root.update()


toast = Toast()

DB_FILE = Path(__file__).parent / "words.json"
SETTINGS_FILE = Path(__file__).parent / "settings.json"

def loadDb():
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text(encoding="utf-8"))
    return {}

def saveDb(db):
    DB_FILE.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")

def loadSettings():
    if not SETTINGS_FILE.exists():
        return None
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return {k: tuple(data[k]) for k in ("result_pt", "cont_pt", "word_region", "answer_region")}
    except (json.JSONDecodeError, KeyError, TypeError):
        print("settings.json is corrupted or incomplete, asking again")
        return None

def saveSettings(settings):
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")

def askSettings():
    return {
        "result_pt": waitForClick("Click a spot that turns red/green to determine correct answer"),
        "word_region": defineRegion("Latin Word"),
        "answer_region": defineRegion("Answers"),
        "cont_pt": waitForClick("Click where the continue button will be"),
    }

def findKey(word, db):
    if word in db:
        return word
    close = difflib.get_close_matches(word, db.keys(), n=1, cutoff=0.85)
    return close[0] if close else None


def waitForClick(pr, suppress=False):
    print(pr)
    toast.show(pr)
    result = {}

    def onClick(x, y, button, pressed):
        if pressed:
            result["pos"] = (x,y)
            return False
    
    with mouse.Listener(on_click=onClick) as listener:
        listener.join()

    print(f"    got {result['pos']}")
    time.sleep(0.3)
    return result["pos"]

def defineRegion(name):
    x1, y1 = waitForClick(f"[{name}] Click the TOP-LEFT corner...", True)
    x2, y2 = waitForClick(f"[{name}] Click the BOTTOM-RIGHT corner...", True)

    left, top = min(x1, x2), min(y1, y2)
    return (left, top, abs(x2-x1), abs(y2-y1))

def getCells(img):
    w,h = img.size
    cells=[]
    for row in range(2):
        for col in range(2):
            cells.append(img.crop((col*w//2, row*h//2, (col+1)*w//2, (row+1)*h//2)))
    
    return cells

def readText(src, lang="eng", psm=7, threshold=False, scale=2):
    img = pyautogui.screenshot(region=src) if isinstance(src, tuple) else src
    img = ImageOps.grayscale(img)
    img = img.resize((img.width*scale, img.height*scale))
    if threshold:
        img = img.point(lambda p: 255 if p > 140 else 0)

    return pytesseract.image_to_string(img, config=f"--psm {psm}", lang=lang).strip().lower()

def cropToText(img, pad=10):
    bbox=ImageOps.invert(img).getbbox()
    if bbox is None:
        return None
    return ImageOps.expand(img.crop(bbox), border=pad, fill=255)

def readLatin(reg):
    return readText(reg, lang="lat", psm=7, threshold=True)

def readCell(img):
    img = ImageOps.grayscale(img)
    img = img.point(lambda p: 0 if p > 200 else 255)
    img = cropToText(img)

    if img is None:
        return ""

    text = readText(img, lang="eng", psm=6, scale=3)
    return " ".join(text.split())

def cellCenter(idx, region):
    left, top, w, h = region
    row, col = divmod(idx, 2)
    return (int(left + (col + 0.5) * w / 2), int(top + (row + 0.5) * h / 2))

def attemptToAnswer(entry, region):
    target = entry["english"]

    ss = pyautogui.screenshot(region=region)
    best_score, best_idx = 0, None
    for idx, cell in enumerate(getCells(ss)):
        text = readCell(cell)
        score = difflib.SequenceMatcher(None, target,text).ratio()
        if score >best_score:
            best_score, best_idx = score, idx
        
    if best_idx is not None and best_score >= MATCH_THRESHOLD:
        pyautogui.click(*cellCenter(best_idx, region))
        print(f"{entry['latin']} -> {target} (MATCH {best_score:.3f})")
        return True
    
    print(f"Couldnt find '{target}' on screen (best {best_score:.3f})")
    toast.show(f"Couldn't find '{target}', click the right one", RED)
    return False

def classifyColor(r,g,b):
    if g>r+40 and g > b + 40:
        return "yes"
    if r > g+40 and r > b+40:
        return "no"
    return None

def getResult(pt):
    x,y=int(pt[0]), int(pt[1])
    img=pyautogui.screenshot(region=(x-2, y-2, 5, 5)).convert("RGB")
    r,g,b = img.resize((1, 1)).getpixel((0, 0))
    return classifyColor(r,g,b)

def waitForResult(pt,timeout=4):
    end = time.time() + timeout
    while time.time() < end:
        res = getResult(pt)
        if res:
            return res
        time.sleep(.01)
    return None

def learnSol(word, key, db, region, result_pt):
    ss = pyautogui.screenshot(region=region)
    cells = getCells(ss)

    x,y=waitForClick(f"Adding dict entry '{word}': click correct answer")

    left,top,w,h = region

    if not (left <= x < left + w and top <= y < top +h):
        toast.show("Click was outside answers area", "RED")
        return
    
    col = 0 if x < left + w / 2 else 1
    row = 0 if y < top + h/2 else 1
    eng = readCell(cells[row * 2+col])


    if not eng:
        toast.show("can not read answer", RED)
        return
    
    time.sleep(.1)
    result = waitForResult(result_pt)

    if result == "yes": 
        db[key] = {"latin":word, "english":eng}
        saveDb(db)
        toast.show(f"Saved {word} -> {eng}")
        print(f"SAVED {word} -> {eng}")
    elif result == "no":
        print(f"Wrong not saving: {word} -> {eng}")
        toast.show("Wrong, not saving", RED)
    else:
        print("UNABLE TO DETERMINE IF CORRECT")
        toast.show("UNABLE TO DETERMINE IF CORRECT")

def clickContinue(result_pt, cont_pt, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        if getResult(result_pt) is None:
            return True
        pyautogui.click(cont_pt[0], cont_pt[1])
        time.sleep(0.03)
    return False

def main():
    settings = None if "--reset" in sys.argv else loadSettings()

    if settings:
        toast.show("Loaded saved settings")
        print("Loaded settings.json")
    else:
        settings = askSettings()
        saveSettings(settings)
        print("Saved settings.json")

    result_pt = settings["result_pt"]
    cont_pt = settings["cont_pt"]
    word_region = settings["word_region"]
    answer_region = settings["answer_region"]

    print(f"\nWords:    {word_region}")
    print(f"\nAnswers:    {answer_region}")
    db = loadDb()
    print("\n Loaded DB")

    ctypes.windll.user32.ShowWindow(
        ctypes.windll.kernel32.GetConsoleWindow(),
        6
    )

    print("\n Watching for words... (CTRL+C TO STOP)\n")
    last = None
    while True:
        toast.tick()

        word = readLatin(word_region)

        if not word or word == last:
            time.sleep(.03)
            continue

        if readLatin(word_region) != word:
            continue

        last = word
        print(f"\n\nDetected: {word}")
        toast.show(f"Detected: {word}")

        key = findKey(word, db)
        if key and attemptToAnswer(db[key], answer_region):
            pass
        else:
            learnSol(word, key or word, db, answer_region, result_pt)
        
        rs = waitForResult(result_pt, 3)
        if rs:
            toast.show("continuing...")
            if not clickContinue(result_pt, cont_pt):
                toast.show("Please press continue", RED)
        else:
            toast.show("No result screen detected, not continuing", RED)
        
        time.sleep(.03)
            

if __name__ == "__main__":
    main()