#!/usr/bin/env python3
"""
Instagram to RSS 2.0 Generator
Target: Akun Publik @pa.sanggau (Pengadilan Agama Sanggau)
"""

import os
import sys
import html
import logging
import tempfile
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

import instaloader

TARGET_USERNAME = os.getenv("IG_USERNAME", "pa.sanggau")
MAX_POSTS = int(os.getenv("MAX_POSTS", "20"))
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "rss.xml")
SESSION_ID = os.getenv("IG_SESSIONID", "").strip()
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


def fetch_instagram_posts(username: str, limit: int) -> tuple[list, str, str]:
    logger.info(f"Menginisialisasi Instaloader untuk akun @{username}...")
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

    # Injeksi cookie session agar tembus blokir cloud data center
    if SESSION_ID:
        logger.info("Session cookie terdeteksi. Memuat sesi login Instagram...")
        loader.context._session.cookies.set("sessionid", SESSION_ID, domain=".instagram.com")
    else:
        logger.info("Berjalan tanpa session cookie.")

    logger.info(f"Mengunduh informasi profil @{username}...")
    profile = instaloader.Profile.from_username(loader.context, username)
    channel_title = f"{profile.full_name or username} (@{username}) - Instagram"
    channel_desc = profile.biography or f"Feed RSS postingan publik Instagram @{username}"

    posts_data = []
    for post in profile.get_posts():
        shortcode = post.shortcode
        link = f"https://www.instagram.com/p/{shortcode}/"
        caption = post.caption or ""
        post_dt = post.date_utc.replace(tzinfo=timezone.utc)
        pub_date = post_dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
        image_url = post.url or ""
        title = generate_title(caption, shortcode)
        desc_html = format_description_html(caption, image_url, link)

        posts_data.append({
            "shortcode": shortcode,
            "title": title,
            "link": link,
            "guid": link,
            "pub_date": pub_date,
            "image_url": image_url,
            "description_html": desc_html,
        })
        if len(posts_data) >= limit:
            break

    return posts_data, channel_title, channel_desc


def main():
    logger.info("=== Memulai Eksekusi Instagram RSS Scraper ===")
    try:
        posts, ch_title, ch_desc = fetch_instagram_posts(TARGET_USERNAME, MAX_POSTS)
        if not posts:
            raise ValueError(f"Tidak ada postingan ditemukan.")

        rss_xml_content = build_rss_xml(posts, ch_title, ch_desc)
        ET.fromstring(rss_xml_content)

        temp_dir = os.path.dirname(os.path.abspath(OUTPUT_FILE))
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=temp_dir, delete=False) as tf:
            tf.write(rss_xml_content)
            temp_name = tf.name

        os.replace(temp_name, OUTPUT_FILE)
        logger.info(f"File RSS berhasil disimpan ke: '{OUTPUT_FILE}' ({len(posts)} postingan).")
        logger.info("=== Selesai dengan Sukses ===")
    except Exception as exc:
        logger.error(f"Terjadi kendala saat memproses data Instagram: {exc}", exc_info=True)
        if os.path.exists(OUTPUT_FILE):
            logger.warning(f"File '{OUTPUT_FILE}' lama tetap dipertahankan.")
            sys.exit(0)
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
