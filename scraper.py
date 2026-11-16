#!/usr/bin/env python3
"""
Instagram to RSS 2.0 Generator
Target: Akun Publik @pa.sanggau (Pengadilan Agama Sanggau)

Fitur:
- Universal Embedded JSON Parser: Menangkap struktur xdt_user_by_username,
  xig_user_by_username, polaris_ordered_timeline_connection, maupun edge_owner_to_timeline_media.
- Melewati login redirect di runner cloud (GitHub Actions) menggunakan session cookie.
- Menghasilkan file rss.xml standar RSS 2.0 yang valid (UTF-8).
- Atomic write: Menjamin berkas rss.xml lama tidak pernah rusak atau terhapus.
"""

import os
import re
import sys
import json
import html
import logging
import tempfile
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

import instaloader

# ==========================================
# KONFIGURASI
# ==========================================
TARGET_USERNAME = os.getenv("IG_USERNAME", "pa.sanggau")
MAX_POSTS = int(os.getenv("MAX_POSTS", "20"))
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "rss.xml")
SESSION_ID = os.getenv("IG_SESSIONID", "").strip()
DS_USER_ID = os.getenv("IG_DS_USER_ID", "").strip()
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("InstagramRSS")


def sanitize_cdata(text: str) -> str:
    if not text:
        return ""
    return text.replace("]]>", "]]]]><![CDATA[>")


def generate_title(caption: str, shortcode: str) -> str:
    if not caption or not caption.strip():
        return f"Postingan Baru Instagram @{TARGET_USERNAME} ({shortcode})"

    clean_text = " ".join(caption.strip().split())
    if len(clean_text) <= 50:
        return clean_text
    
    return clean_text[:47].rstrip() + "..."


def format_description_html(caption: str, image_url: str, post_link: str) -> str:
    html_parts = ['<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; line-height: 1.6;">']

    if image_url:
        html_parts.append(
            f'<p><a href="{html.escape(post_link)}" target="_blank" rel="noopener noreferrer">'
            f'<img src="{html.escape(image_url)}" '
            f'alt="Postingan Instagram @{html.escape(TARGET_USERNAME)}" '
            f'referrerpolicy="no-referrer" '
            f'style="max-width: 100%; height: auto; border-radius: 8px; display: block; margin-bottom: 14px;" />'
            f'</a></p>'
        )

    if caption and caption.strip():
        paragraphs = caption.strip().split("\n\n")
        for para in paragraphs:
            para_clean = para.strip()
            if para_clean:
                lines = [html.escape(line) for line in para_clean.splitlines()]
                formatted_para = "<br/>".join(lines)
                html_parts.append(f'<p style="margin-bottom: 10px;">{formatted_para}</p>')
    else:
        html_parts.append('<p><em>(Tidak ada caption teks)</em></p>')

    html_parts.append(
        f'<p><small><a href="{html.escape(post_link)}" target="_blank" rel="noopener noreferrer">'
        f'Lihat postingan asli di Instagram &rarr;</a></small></p>'
    )
    html_parts.append('</div>')

    return "\n".join(html_parts)


def build_rss_xml(posts: list, channel_title: str, channel_desc: str) -> str:
    now_rfc822 = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    profile_url = f"https://www.instagram.com/{TARGET_USERNAME}/"

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        '  <channel>',
        f'    <title>{html.escape(channel_title)}</title>',
        f'    <link>{html.escape(profile_url)}</link>',
        f'    <description>{html.escape(channel_desc)}</description>',
        '    <language>id-ID</language>',
        f'    <lastBuildDate>{now_rfc822}</lastBuildDate>',
        '    <generator>Custom Instagram RSS Python Automation</generator>',
    ]

    for post in posts:
        title = html.escape(post["title"])
        link = html.escape(post["link"])
        guid = html.escape(post["guid"])
        pub_date = post["pub_date"]
        desc_cdata = sanitize_cdata(post["description_html"])

        xml_lines.append('    <item>')
        xml_lines.append(f'      <title>{title}</title>')
        xml_lines.append(f'      <link>{link}</link>')
        xml_lines.append(f'      <guid isPermaLink="true">{guid}</guid>')
        xml_lines.append(f'      <pubDate>{pub_date}</pubDate>')
        xml_lines.append(f'      <description><![CDATA[{desc_cdata}]]></description>')

        if post.get("image_url"):
            enclosure_url = html.escape(post["image_url"])
            xml_lines.append(f'      <enclosure url="{enclosure_url}" length="0" type="image/jpeg" />')

        xml_lines.append('    </item>')

    xml_lines.append('  </channel>')
    xml_lines.append('</rss>\n')

    return "\n".join(xml_lines)


def parse_post_node(node: dict) -> dict:
    code = node.get("code") or node.get("shortcode")
    link = f"https://www.instagram.com/p/{code}/"
    
    caption_obj = node.get("caption")
    if isinstance(caption_obj, dict):
        caption = caption_obj.get("text", "")
    elif isinstance(caption_obj, str):
        caption = caption_obj
    else:
        caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
        if caption_edges and isinstance(caption_edges[0], dict):
            caption = caption_edges[0].get("node", {}).get("text", "")
        else:
            caption = ""

    # Konversi ID Snowflake Instagram ke waktu publikasi RFC-822 yang akurat
    pk = node.get("pk")
    if pk:
        ts = ((int(pk) >> 23) + 1314220021794) / 1000.0
        post_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    elif node.get("taken_at_timestamp"):
        post_dt = datetime.fromtimestamp(node["taken_at_timestamp"], tz=timezone.utc)
    else:
        post_dt = datetime.now(timezone.utc)

    pub_date = post_dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
    image_url = node.get("display_uri") or node.get("display_url") or ""

    title = generate_title(caption, code)
    desc_html = format_description_html(caption, image_url, link)

    return {
        "shortcode": code,
        "title": title,
        "link": link,
        "guid": link,
        "pub_date": pub_date,
        "image_url": image_url,
        "description_html": desc_html,
    }


def universal_extract_posts(html_text: str) -> tuple[dict, list]:
    """
    Ekstraksi rekursif universal dari seluruh script JSON di dalam HTML Instagram.
    Mendukung format xdt_user_by_username, xig_user_by_username, polaris, maupun edge_owner.
    """
    scripts = re.findall(r'<script type=[\x22\x27]application/json[\x22\x27][^>]*>(.*?)</script>', html_text, re.DOTALL)
    logger.info(f"Ditemukan {len(scripts)} blok data JSON tertanam di halaman.")

    user_info = {}
    edges = []

    def recursive_search(obj):
        nonlocal user_info, edges
        if isinstance(obj, dict):
            # 1. Cari data profil user
            for u_key in ["xdt_user_by_username", "xig_user_by_username", "user"]:
                if u_key in obj and isinstance(obj[u_key], dict):
                    cand = obj[u_key]
                    if cand.get("full_name") or cand.get("biography") or cand.get("pk"):
                        user_info.update(cand)

            # 2. Cari timeline postingan
            for tl_key in ["polaris_ordered_timeline_connection", "edge_owner_to_timeline_media", "ordered_timeline_connection"]:
                if tl_key in obj and isinstance(obj[tl_key], dict):
                    tl = obj[tl_key]
                    if "edges" in tl and isinstance(tl["edges"], list):
                        for e in tl["edges"]:
                            if isinstance(e, dict) and "node" in e:
                                edges.append(e)

            # 3. Cari jika obj sendiri adalah container edges
            if "edges" in obj and isinstance(obj["edges"], list):
                if obj["edges"] and isinstance(obj["edges"][0], dict):
                    first_node = obj["edges"][0].get("node")
                    if isinstance(first_node, dict) and ("code" in first_node or "shortcode" in first_node):
                        edges.extend(obj["edges"])

            for v in obj.values():
                recursive_search(v)
        elif isinstance(obj, list):
            for item in obj:
                recursive_search(item)

    for s in scripts:
        try:
            data = json.loads(s)
            recursive_search(data)
        except Exception:
            continue

    # Hapus duplikat postingan berdasarkan shortcode
    unique_edges = []
    seen_codes = set()
    for e in edges:
        node = e.get("node", {})
        code = node.get("code") or node.get("shortcode")
        if code and code not in seen_codes:
            seen_codes.add(code)
            unique_edges.append(e)

    return user_info, unique_edges


def fetch_instagram_posts(username: str, limit: int) -> tuple[list, str, str]:
    logger.info(f"Menginisialisasi request profil @{username}...")
    
    loader = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        user_agent=USER_AGENT,
        quiet=True
    )

    # Injeksi cookie session
    if SESSION_ID:
        logger.info("Session cookie terdeteksi. Memuat cookie autentikasi...")
        if "=" in SESSION_ID:
            for part in SESSION_ID.split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    k_clean = k.strip()
                    v_clean = v.strip().strip('"')
                    loader.context._session.cookies.set(k_clean, v_clean, domain=".instagram.com")
                    loader.context._session.cookies.set(k_clean, v_clean, domain="www.instagram.com")
        else:
            for domain in [".instagram.com", "www.instagram.com", ""]:
                kwargs = {"domain": domain} if domain else {}
                loader.context._session.cookies.set("sessionid", SESSION_ID, **kwargs)
                if DS_USER_ID:
                    loader.context._session.cookies.set("ds_user_id", DS_USER_ID, **kwargs)

        loader.context._session.headers.update({
            "x-ig-app-id": "936619743392459",
            "Referer": "https://www.instagram.com/",
        })
    else:
        logger.info("Berjalan tanpa session cookie.")

    # Override get_anonymous_session agar cookie sesi tidak dihapus
    loader.context.get_anonymous_session = lambda: loader.context._session

    logger.info(f"Mengunduh dokumen web profil @{username}...")
    html_content = loader.context._get_page(loader.context._session, f"{username.lower()}/")
    
    user_info, edges = universal_extract_posts(html_content)

    full_name = user_info.get("full_name") or "Pengadilan Agama Sanggau"
    biography = user_info.get("biography") or f"Feed RSS postingan publik Instagram @{username}"
    channel_title = f"{full_name} (@{username}) - Instagram"
    channel_desc = biography

    logger.info(f"Profil: '{full_name}'. Ditemukan {len(edges)} postingan di halaman web.")

    posts_data = []
    for edge in edges:
        node = edge.get("node", {})
        if node:
            posts_data.append(parse_post_node(node))
            if len(posts_data) >= limit:
                break

    # Jika butuh arsip postingan lebih banyak, coba panggil profile.get_posts()
    if len(posts_data) < limit:
        try:
            logger.info("Mencoba mengambil arsip postingan lanjutan...")
            profile = instaloader.Profile.from_username(loader.context, username)
            for p in profile.get_posts():
                if any(item["shortcode"] == p.shortcode for item in posts_data):
                    continue
                
                p_dt = p.date_utc.replace(tzinfo=timezone.utc)
                posts_data.append({
                    "shortcode": p.shortcode,
                    "title": generate_title(p.caption or "", p.shortcode),
                    "link": f"https://www.instagram.com/p/{p.shortcode}/",
                    "guid": f"https://www.instagram.com/p/{p.shortcode}/",
                    "pub_date": p_dt.strftime("%a, %d %b %Y %H:%M:%S GMT"),
                    "image_url": p.url or "",
                    "description_html": format_description_html(p.caption or "", p.url or "", f"https://www.instagram.com/p/{p.shortcode}/"),
                })
                if len(posts_data) >= limit:
                    break
        except Exception as more_err:
            logger.warning(f"Arsip tambahan tidak tersedia ({more_err}), menggunakan {len(posts_data)} postingan utama.")

    return posts_data, channel_title, channel_desc


def main():
    logger.info("=== Memulai Eksekusi Instagram RSS Scraper ===")
    
    try:
        posts, ch_title, ch_desc = fetch_instagram_posts(TARGET_USERNAME, MAX_POSTS)
        
        if not posts:
            raise ValueError(f"Tidak ada postingan yang ditemukan untuk profil @{TARGET_USERNAME}.")

        logger.info("Menyusun format dokumen RSS 2.0...")
        rss_xml_content = build_rss_xml(posts, ch_title, ch_desc)

        try:
            ET.fromstring(rss_xml_content)
            logger.info("Validasi sintaks XML berhasil: Well-formed RSS 2.0.")
        except ET.ParseError as pe:
            raise RuntimeError(f"Gagal memvalidasi XML yang dihasilkan: {pe}")

        temp_dir = os.path.dirname(os.path.abspath(OUTPUT_FILE))
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=temp_dir, delete=False) as tf:
            tf.write(rss_xml_content)
            temp_name = tf.name

        os.replace(temp_name, OUTPUT_FILE)
        logger.info(f"File RSS berhasil disimpan ke: '{OUTPUT_FILE}' ({len(posts)} postingan).")
        logger.info("=== Eksekusi Selesai dengan Sukses ===")

    except Exception as exc:
        logger.error(f"Terjadi kendala saat memproses data Instagram: {exc}", exc_info=True)
        if os.path.exists(OUTPUT_FILE):
            logger.warning(
                f"File '{OUTPUT_FILE}' yang sudah ada dipertahankan agar feed tidak hilang."
            )
            sys.exit(0)
        else:
            logger.error(f"File '{OUTPUT_FILE}' belum ada dan proses scraping gagal. Berhenti.")
            sys.exit(1)


if __name__ == "__main__":
    main()
