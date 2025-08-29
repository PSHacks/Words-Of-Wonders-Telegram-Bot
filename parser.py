import sqlite3
import requests
import time
import random
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://bygame.ru"
START_PAGE = "https://bygame.ru/otvety/wow"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36"
}

PROGRESS_DB = "progress.db"  # для ссылок на страницы с уровнями
LEVELS_DB = "levels.db"      # для самих уровней

# --- Инициализация базы с прогрессом ---
def init_progress_db():
    conn = sqlite3.connect(PROGRESS_DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            url TEXT PRIMARY KEY,
            processed BOOLEAN NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

# --- Инициализация базы с уровнями ---
def init_levels_db():
    conn = sqlite3.connect(LEVELS_DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS levels (
            level INTEGER PRIMARY KEY,
            main_words TEXT NOT NULL,
            bonus_words TEXT
        )
    """)
    conn.commit()
    conn.close()

# --- Сохраняем ссылки на страницы в progress.db ---
def save_links(urls):
    conn = sqlite3.connect(PROGRESS_DB)
    c = conn.cursor()
    for url in urls:
        try:
            c.execute("INSERT OR IGNORE INTO pages (url) VALUES (?)", (url,))
        except Exception as e:
            print(f"Ошибка при вставке ссылки {url}: {e}")
    conn.commit()
    conn.close()

# --- Получаем список ссылок для обработки ---
def get_unprocessed_links():
    conn = sqlite3.connect(PROGRESS_DB)
    c = conn.cursor()
    c.execute("SELECT url FROM pages WHERE processed = 0")
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

# --- Отмечаем ссылку как обработанную ---
def mark_processed(url):
    conn = sqlite3.connect(PROGRESS_DB)
    c = conn.cursor()
    c.execute("UPDATE pages SET processed = 1 WHERE url = ?", (url,))
    conn.commit()
    conn.close()

# --- Сохраняем уровни в levels.db ---
def save_level(level_num, main_words, bonus_words):
    conn = sqlite3.connect(LEVELS_DB)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO levels (level, main_words, bonus_words) VALUES (?, ?, ?)
    """, (level_num, ",".join(main_words), ",".join(bonus_words) if bonus_words else None))
    conn.commit()
    conn.close()

# --- Получаем все ссылки с главной страницы ---
def get_all_links():
    print("🔎 Получаем все ссылки на страницы с уровнями...")
    r = requests.get(START_PAGE, headers=HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    links = []
    # Ищем все ссылки вида /otvety/wow-...
    for a in soup.select("li > a.uk-button"):
        href = a.get("href", "")
        if href.startswith("/otvety/wow-"):
            full_url = BASE_URL + href
            links.append(full_url)
    print(f"Найдено {len(links)} ссылок.")
    return links

# --- Парсим страницу с уровнями ---
def parse_level_page(url):
    print(f"Парсим страницу: {url}")
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Собираем все уровни и ответы на странице
    results = []
    headers = soup.find_all("h2", class_="uk-h3")
    for h2 in headers:
        title = h2.get_text(strip=True)
        if not title.startswith("Уровень"):
            continue
        try:
            level_num = int(title.split()[1])
        except:
            continue

        # Следующий sibling <p> с ответами
        p = h2.find_next_sibling("p")
        if not p:
            continue

        # В p есть сильное выделение <strong> - можно игнорировать
        # Основные слова идут сразу после <strong> (текст), бонусные - в <span>
        strong = p.find("strong")
        # Текст после strong (и <br>)
        text_nodes = []
        for elem in strong.next_siblings:
            if elem.name == "br":
                continue
            if isinstance(elem, str):
                text_nodes.append(elem.strip())
            elif elem.name == "span":
                # bonus
                continue
        main_words_text = " ".join(text_nodes).replace("\n", " ").replace(",", " ")
        main_words = [w.strip().upper() for w in main_words_text.split() if w.strip()]

        # бонусные слова
        bonus_words = []
        span = p.find("span", class_="uk-text-meta")
        if span:
            bonus_text = span.get_text(separator=",").replace("\n", " ")
            bonus_words = [w.strip().upper() for w in bonus_text.split(",") if w.strip()]

        results.append((level_num, main_words, bonus_words))
    return results

def worker(url):
    try:
        levels = parse_level_page(url)
        for level_num, main_words, bonus_words in levels:
            save_level(level_num, main_words, bonus_words)
        mark_processed(url)
        time.sleep(random.uniform(0.5, 1.5))
        return True, url
    except Exception as e:
        print(f"Ошибка при обработке {url}: {e}")
        return False, url

def main():
    init_progress_db()
    init_levels_db()

    # При первом запуске сохраняем все ссылки
    conn = sqlite3.connect(PROGRESS_DB)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM pages")
    count = c.fetchone()[0]
    conn.close()

    if count == 0:
        links = get_all_links()
        save_links(links)

    # Получаем количество потоков от пользователя
    try:
        threads = int(input("Введите количество потоков (макс 10): "))
        if threads < 1:
            threads = 1
        elif threads > 10:
            threads = 10
    except:
        threads = 5
    print(f"Запускаем парсер с {threads} потоками...")

    links_to_process = get_unprocessed_links()
    print(f"Ссылок для обработки: {len(links_to_process)}")

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(worker, url): url for url in links_to_process}
        for future in as_completed(futures):
            success, url = future.result()
            if success:
                print(f"✅ Обработано: {url}")
            else:
                print(f"❌ Ошибка: {url}")

if __name__ == "__main__":
    main()
