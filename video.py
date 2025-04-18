import requests
import aria2p
from datetime import datetime
from status import format_progress_bar
import asyncio
import os, time
import logging
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, RPCError

aria2 = aria2p.API(
    aria2p.Client(
        host="http://localhost",
        port=6800,
        secret=""
    )
)
options = {
    "max-tries": "50",
    "retry-wait": "3",
    "continue": "true",
    "dir": "/tmp/terabox_downloads"
}
aria2.set_global_options(options)
os.makedirs(options["dir"], exist_ok=True)

async def download_video(url, reply_msg, user_mention, user_id):
    download = None
    thumbnail_path = None
    try:
        response = requests.get(f"https://teraboxdl.tellycloudapi.workers.dev/?url={url}", timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data.get("Data"):
            raise ValueError("Invalid API response format")

        resolutions = data["Data"]
        fast_link = resolutions.get("DirectLink")
        hd_link = resolutions.get("DirectLink2")
        thumbnail_url = (resolutions.get("Thum") or [{}])[0].get("360x270")
        video_title = resolutions.get("FileName", "video").replace("/", "_")

        if not fast_link and not hd_link:
            raise ValueError("No valid download links found")

        download_url = fast_link or hd_link
        download = aria2.add_uris([download_url], options={"dir": options["dir"]})
        start_time = datetime.now()
        last_update = time.time()

        while not download.is_complete:
            await asyncio.sleep(2)
            download.update()

            if download.status == "error":
                raise aria2p.ClientException(f"Download error: {download.error_message}")
            if download.is_paused:
                raise aria2p.ClientException("Download was paused unexpectedly")

            if time.time() - last_update > 2:
                progress_text = format_progress_bar(
                    filename=video_title,
                    percentage=download.progress,
                    done=download.completed_length,
                    total_size=download.total_length,
                    status=download.status.capitalize(),
                    eta=download.eta,
                    speed=download.download_speed,
                    elapsed=(datetime.now() - start_time).total_seconds(),
                    user_mention=user_mention,
                    user_id=user_id,
                    aria2p_gid=download.gid
                )
                try:
                    await reply_msg.edit_text(progress_text)
                    last_update = time.time()
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                except RPCError:
                    pass

        if not os.path.exists(download.files[0].path):
            raise FileNotFoundError("Downloaded file not found")

        if thumbnail_url:
            try:
                thumb_response = requests.get(thumbnail_url, timeout=10)
                thumb_response.raise_for_status()
                thumbnail_path = os.path.join(options["dir"], "thumbnail.jpg")
                with open(thumbnail_path, "wb") as f:
                    f.write(thumb_response.content)
            except Exception as e:
                logging.warning(f"Thumbnail download failed: {e}")
                thumbnail_path = None

        return download.files[0].path, thumbnail_path, video_title

    except Exception as e:
        logging.error(f"Download failed: {str(e)}", exc_info=True)
        if download and not download.is_removed:
            try:
                download.remove(force=True, files=True)
            except Exception as ce:
                logging.error(f"Cleanup failed: {ce}")

        buttons = []
        if hd_link:
            buttons.append([InlineKeyboardButton("🚀 HD Video", url=hd_link)])
        if fast_link and fast_link != hd_link:
            buttons.append([InlineKeyboardButton("⚡ Fast Download", url=fast_link)])

        markup = InlineKeyboardMarkup(buttons) if buttons else None
        try:
            await reply_msg.edit_text("❌ Download failed. Please try again or use manual links below.", reply_markup=markup)
        except RPCError:
            pass

        return None, None, None

async def upload_video(client, file_path, thumbnail_path, video_title, reply_msg, collection_channel_id, user_mention, user_id, message):
    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError("Downloaded file not found")

        file_size = os.path.getsize(file_path)
        start_time = datetime.now()
        last_update = time.time()

        async def progress(current, total):
            nonlocal last_update
            now = time.time()
            if now - last_update > 2:
                percent = (current / total) * 100
                elapsed = (datetime.now() - start_time).total_seconds()
                speed = current / elapsed if elapsed else 0
                eta = (total - current) / speed if speed else 0

                progress_text = format_progress_bar(
                    filename=video_title,
                    percentage=percent,
                    done=current,
                    total_size=total,
                    status="Uploading",
                    eta=eta,
                    speed=speed,
                    elapsed=elapsed,
                    user_mention=user_mention,
                    user_id=user_id
                )
                try:
                    await reply_msg.edit_text(progress_text)
                    last_update = now
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                except RPCError:
                    pass

        if not (thumbnail_path and os.path.exists(thumbnail_path)):
            thumbnail_path = None

        try:
            collection_msg = await client.send_video(
                chat_id=collection_channel_id,
                video=file_path,
                caption=f"✨ {video_title}\n👤 ʟᴇᴇᴄʜᴇᴅ ʙʏ : {user_mention}\n📥 ᴜsᴇʀ ʟɪɴᴋ: tg://user?id={user_id}",
                thumb=thumbnail_path,
                progress=progress,
                supports_streaming=True
            )
        except FloodWait as e:
            await asyncio.sleep(e.value)
            collection_msg = await client.send_video(
                chat_id=collection_channel_id,
                video=file_path,
                caption=f"✨ {video_title}\n👤 ʟᴇᴇᴄʜᴇᴅ ʙʏ : {user_mention}\n📥 ᴜsᴇʀ ʟɪɴᴋ: tg://user?id={user_id}",
                thumb=thumbnail_path,
                progress=progress,
                supports_streaming=True
            )

        await client.copy_message(
            chat_id=message.chat.id,
            from_chat_id=collection_channel_id,
            message_id=collection_msg.id
        )

        try:
            await message.delete()
            await reply_msg.delete()
            sticker = await message.reply_sticker("CAACAgIAAxkBAAEZdwRmJhCNfFRnXwR_lVKU1L9F3qzbtAAC4gUAAj-VzApzZV-v3phk4DQE")
            await asyncio.sleep(5)
            await sticker.delete()
        except RPCError:
            pass

        return collection_msg.id

    except Exception as e:
        logging.error(f"Upload failed: {str(e)}", exc_info=True)
        try:
            await reply_msg.edit_text("❌ Upload failed. Please try again later.")
        except RPCError:
            pass
        return None

    finally:
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
            if thumbnail_path and os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
        except Exception as cleanup_err:
            logging.error(f"File cleanup failed: {cleanup_err}")
