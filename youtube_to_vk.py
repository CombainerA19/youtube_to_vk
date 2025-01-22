import os
import time
import configparser
from datetime import datetime
import vk_api
from vk_api.upload import VkUpload
from yt_dlp import YoutubeDL

CONFIG_FILE = "vk_config.ini"
URLS_FILE = "youtube_urls.txt"
LOGS_FILE = "logs.txt"
DOWNLOAD_DIR = "downloads"

def create_files():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as cfg:
            cfg.write("[VK]\naccess_token=\ntargets=\n")
    if not os.path.exists(URLS_FILE):
        with open(URLS_FILE, 'w', encoding='utf-8') as f:
            f.write("")
    if not os.path.exists(LOGS_FILE):
        with open(LOGS_FILE, 'w', encoding='utf-8') as lf:
            lf.write("date time | status | youtube url | video title | target id | target name | target type\n")

def read_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE, encoding='utf-8')
    token = config.get("VK", "access_token", fallback="").strip()
    targets_str = config.get("VK", "targets", fallback="").strip()
    targets = [t.strip() for t in targets_str.split(',') if t.strip()]
    return token, targets

def read_urls():
    if os.path.exists(URLS_FILE):
        with open(URLS_FILE, 'r', encoding='utf-8') as file:
            return [line.strip() for line in file if line.strip()]
    return []

def fix_double_encoding(s: str) -> str:
    """
    Пробуем вычислить «двойную» кодировку, часто встречающуюся
    при неправильной интерпретации русских букв.
    Если попытка неудачна, возвращаем исходную строку.
    При необходимости меняйте 'latin-1' на 'cp1251' и т.п.
    """
    if not s:
        return s
    try:
        # Интерпретируем текущий текст как latin-1 и декодируем в utf-8
        decoded = s.encode('latin-1', errors='replace').decode('utf-8', errors='replace')
        # Если получилось сплошное «�», то декодирование неудачное
        if decoded.count('�') > len(s) // 2:
            # Слишком много кракозябр, вернём оригинал
            return s
        return decoded
    except:
        return s

def log_event(status, youtube_url, video_title, target_id, target_name, target_type):
    # Чиним только target_name (часто именно имена ВК оказываются закодированы дважды).
    # Если нужно чинить и video_title — примените fix_double_encoding и к нему.
    target_name_fixed = fix_double_encoding(target_name)
    # Если нужно — раскомментируйте строку ниже:
    # video_title_fixed = fix_double_encoding(video_title)

    with open(LOGS_FILE, 'a', encoding='utf-8') as logs:
        logs.write(
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {status} | {youtube_url} | {video_title} | "
            f"{target_id} | {target_name_fixed} | {target_type}\n"
        )

def get_target_info(vk_session, target_id):
    try:
        if target_id.startswith('-'):
            group_id = target_id.lstrip('-')
            response = vk_session.method('groups.getById', {'group_id': group_id})
            group_name = response[0]['name']
            return group_name, "группа"
        else:
            user_id = target_id
            response = vk_session.method('users.get', {'user_ids': user_id})
            first_name = response[0]['first_name']
            last_name = response[0]['last_name']
            return f"{first_name} {last_name}", "личная страница"
    except Exception as e:
        print(f"[ERROR] Failed to get info for {target_id}: {e}")
        return "Unknown", "unknown"

def download_youtube_video(url):
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    ydl_opts = {
        'outtmpl': f'{DOWNLOAD_DIR}/%(id)s.%(ext)s',
        'format': 'best[ext=mp4]',
        'nocheckcertificate': True,
        'prefer_insecure': True
    }
    print(f"[INFO] Downloading from {url}")
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        video_id = info.get("id", "unknown_id")
        file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")
        raw_title = info.get("title", "Unknown Title")
        raw_desc = info.get("description", "") or ""
    return file_path, raw_title, raw_desc

def upload_to_vk(vk_session, video_path, video_title, video_description, target_id):
    target_name, target_type = get_target_info(vk_session, target_id)
    print(f"[INFO] Uploading to: {target_id} ({target_name} / {target_type}) | Title: {video_title}")
    upload = VkUpload(vk_session)
    try:
        if target_type == "группа":
            upload.video(
                video_file=video_path,
                group_id=target_id.lstrip('-'),
                name=video_title,
                description=video_description
            )
        else:
            upload.video(
                video_file=video_path,
                name=video_title,
                description=video_description
            )
        print(f"[INFO] Success -> {target_id} ({target_name})")
        return True, target_name, target_type
    except vk_api.exceptions.ApiError as e:
        print(f"[ERROR] VK upload failed -> {target_id}: {e}")
        return False, target_name, target_type

def remove_processed_urls(processed_urls):
    if not processed_urls:
        return
    with open(URLS_FILE, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip()]
    with open(URLS_FILE, 'w', encoding='utf-8') as f:
        for line in lines:
            if line not in processed_urls:
                f.write(line + '\n')
    print(f"[INFO] Removed URLs: {processed_urls}")

def main():
    create_files()
    token, targets = read_config()
    if not token or not targets:
        print("[ERROR] Token or targets not set. Check vk_config.ini.")
        return

    vk_session = vk_api.VkApi(token=token)

    while True:
        urls = read_urls()
        if not urls:
            print("[INFO] No URLs to process. Sleeping 10 minutes...")
            time.sleep(600)
            continue

        processed_urls = []
        for url in urls:
            print(f"[INFO] Processing URL: {url}")
            try:
                file_path, video_title, video_desc = download_youtube_video(url)

                any_success = False
                for t_id in targets:
                    ok, tgt_name, tgt_type = upload_to_vk(
                        vk_session,
                        file_path,
                        video_title,
                        video_desc,
                        t_id
                    )
                    if ok:
                        log_event("SUCCESS", url, video_title, t_id, tgt_name, tgt_type)
                        any_success = True
                    else:
                        log_event("ERROR", url, video_title, t_id, tgt_name, tgt_type)

                if os.path.exists(file_path):
                    os.remove(file_path)

                if any_success:
                    processed_urls.append(url)
                else:
                    print(f"[ERROR] No successful uploads for {url}")

            except Exception as e:
                print(f"[ERROR] Exception for {url}: {e}")
                with open(LOGS_FILE, 'a', encoding='utf-8') as logs:
                    logs.write(
                        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | ERROR | {url} | Unknown Title | - | - | - | Exception: {e}\n"
                    )

        remove_processed_urls(processed_urls)
        print("[INFO] Finished batch. Sleeping 10 minutes...")
        time.sleep(600)

if __name__ == "__main__":
    main()
