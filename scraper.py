#!/usr/bin/env python3
"""
Instagram to RSS 2.0 Generator
Target: Akun Publik @pa.sanggau (Pengadilan Agama Sanggau)

Fitur Utama:
- Mengambil metadata postingan publik terbaru tanpa login.
- Menghasilkan file rss.xml standar RSS 2.0 yang valid (UTF-8).
- Elemen lengkap: <title>, <link>, <guid>, <pubDate>, <description> (CDATA + <img>), dan <enclosure>.
- Ketahanan / Atomic Write: Berkas rss.xml lama tetap aman jika koneksi terputus atau kena rate-limit.
"""

import os
import sys
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
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Konfigurasi Logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("InstagramRSS")


def sanitize_cdata(text: str) -> str:
    """Mencegah rusaknya format CDATA jika terdapat karakter ']]>' pada caption."""
    if not text:
        return ""
    return text.replace("]]>", "]]]]><![CDATA[>")


def generate_title(caption: str, shortcode: str) -> str:
    """
    Menghasilkan judul sesuai spesifikasi:
    50 karakter pertama dari caption yang bersih, atau fallback ke shortcode.
    """
    if not caption or not caption.strip():
        return f"Postingan Baru Instagram @{TARGET_USERNAME} ({shortcode})"

    # Normalisasi spasi dan baris baru
    clean_text = " ".join(caption.strip().split())
    if len(clean_text) <= 50:
        return clean_text
    
    # Ambil 47 karakter pertama + elipsis '...' (total 50 karakter)
    return clean_text[:47].rstrip() + "..."


def format_description_html(caption: str, image_url: str, post_link: str) -> str:
    """
    Menyusun HTML di dalam <description> dengan gambar <img> responsif dan teks berparagraf.
    """
    html_parts = ['<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; line-height: 1.6;">']

    # Tag gambar jika URL media tersedia
    if image_url:
        html_parts.append(
            f'<p><a href="{html.escape(post_link)}" target="_blank" rel="noopener noreferrer">'
            f'<img src="{html.escape(image_url)}" '
            f'alt="Postingan Instagram @{html.escape(TARGET_USERNAME)}" '
            f'referrerpolicy="no-referrer" '
            f'style="max-width: 100%; height: auto; border-radius: 8px; display: block; margin-bottom: 14px;" />'
            f'</a></p>'
        )

    # Format teks caption menjadi paragraf HTML rapi
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

    # Tautan ke postingan asli
    html_parts.append(
        f'<p><small><a href="{html.escape(post_link)}" target="_blank" rel="noopener noreferrer">'
        f'Lihat postingan asli di Instagram &rarr;</a></small></p>'
    )
    html_parts.append('</div>')

    return "\n".join(html_parts)


def build_rss_xml(posts: list, channel_title: str, channel_desc: str) -> str:
    """
    Menyusun dokumen standar RSS 2.0 lengkap.
    """
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

        # Enclosure media untuk kompatibilitas pembaca berita / podcast / agregator
        if post.get("image_url"):
            enclosure_url = html.escape(post["image_url"])
            xml_lines.append(f'      <enclosure url="{enclosure_url}" length="0" type="image/jpeg" />')

        xml_lines.append('    </item>')

    xml_lines.append('  </channel>')
    xml_lines.append('</rss>\n')

    return "\n".join(xml_lines)


def fetch_instagram_posts(username: str, limit: int) -> tuple[list, str, str]:
    """
    Mengambil metadata postingan publik profil Instagram menggunakan Instaloader.
    """
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

    logger.info(f"Mengunduh informasi profil publik @{username}...")
    profile = instaloader.Profile.from_username(loader.context, username)
    
    channel_title = f"{profile.full_name or username} (@{username}) - Instagram"
    channel_desc = profile.biography or f"Feed RSS postingan publik Instagram @{username}"

    logger.info(f"Profil ditemukan: '{profile.full_name}'. Mengambil maksimal {limit} postingan...")

    posts_data = []
    for post in profile.get_posts():
        shortcode = post.shortcode
        link = f"https://www.instagram.com/p/{shortcode}/"
        caption = post.caption or ""
        
        # Konversi waktu publikasi ke format standar RFC-822 (GMT)
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

    logger.info(f"Berhasil mengambil {len(posts_data)} postingan terbaru dari @{username}.")
    return posts_data, channel_title, channel_desc


def main():
    logger.info("=== Memulai Eksekusi Instagram RSS Scraper ===")
    
    try:
        posts, ch_title, ch_desc = fetch_instagram_posts(TARGET_USERNAME, MAX_POSTS)
        
        if not posts:
            raise ValueError(f"Tidak ada postingan yang ditemukan untuk profil @{TARGET_USERNAME}.")

        logger.info("Menyusun format dokumen RSS 2.0...")
        rss_xml_content = build_rss_xml(posts, ch_title, ch_desc)

        # Validasi struktur XML sebelum ditulis ke disk
        try:
            ET.fromstring(rss_xml_content)
            logger.info("Validasi sintaks XML berhasil: Well-formed RSS 2.0.")
        except ET.ParseError as pe:
            raise RuntimeError(f"Gagal memvalidasi XML yang dihasilkan: {pe}")

        # Tulis secara aman menggunakan file sementara (atomic write)
        temp_dir = os.path.dirname(os.path.abspath(OUTPUT_FILE))
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=temp_dir, delete=False) as tf:
            tf.write(rss_xml_content)
            temp_name = tf.name

        # Menggantikan file secara atomik (tidak akan merusak file jika crash)
        os.replace(temp_name, OUTPUT_FILE)
        logger.info(f"File RSS berhasil disimpan ke: '{OUTPUT_FILE}' ({len(posts)} postingan).")
        logger.info("=== Eksekusi Selesai dengan Sukses ===")

    except Exception as exc:
        logger.error(f"Terjadi kendala saat memproses data Instagram: {exc}", exc_info=True)
        
        # Ketahanan: Jika file rss.xml sudah pernah ada, pertahankan file tersebut
        if os.path.exists(OUTPUT_FILE):
            logger.warning(
                f"File '{OUTPUT_FILE}' yang sudah ada dipertahankan agar feed tidak hilang."
            )
            # Exit code 0 agar action tidak dianggap fail jika hanya terkena rate-limit sesaat
            sys.exit(0)
        else:
            logger.error(f"File '{OUTPUT_FILE}' belum ada dan proses scraping gagal. Berhenti.")
            sys.exit(1)


if __name__ == "__main__":
    main()
