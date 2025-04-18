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
    "dir": "/tmp/terabox_downloads"  # Add dedicated download directory
}

aria2.set_global_options(options)

# Create download directory if not exists
os.makedirs(options["dir"], exist_ok=True)

async def download_video(url, reply_msg, user_mention, user_id):
    download = None
    thumbnail_path = None
    try:
        # Get video metadata from the API
        response = requests.get(f"https://teraboxdl.tellycloudapi.workers.dev/?url={url}", timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data.get("Data"):
            raise ValueError("Invalid API response format")

        resolutions = data["Data"]
        fast_download_link = resolutions.get("DirectLink")
        hd_download_link = resolutions.get("DirectLink2")
        thumbnail_url = (resolutions.get("Thum") or [{}])[0].get("360x270")  # Handle empty Thum list
        video_title = resolutions.get("FileName", "video").replace("/", "_")  # Sanitize filename

        if not fast_download_link:
            if hd_download_link:
                fast_download_link = hd_download_link
            else:
                raise ValueError("No valid download links found")

        # Start download via aria2
        download = aria2.add_uris([fast_download_link], options={"dir": options["dir"]})
        start_time = datetime.now()
        last_update = time.time()

        while not download.is_complete:
            await asyncio.sleep(2)
            download.update()
            
            if download.status == "error":
                raise aria2p.ClientException(f"Download error: {download.error_message}")
                
            if download.is_paused:
                raise aria2p.ClientException("Download was paused unexpectedly")

            # Throttle progress updates to avoid flooding
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

        # Verify downloaded file
        if not download.is_complete or not os.path.exists(download.files[0].path):
            raise FileNotFoundError("Downloaded file not found")

        # Download thumbnail
        thumbnail_path = os.path.join(options["dir"], "thumbnail.jpg")
        if thumbnail_url:
            try:
                thumb_response = requests.get(thumbnail_url, timeout=10)
                thumb_response.raise_for_status()
                with open(thumbnail_path, "wb") as thumb_file:
                    thumb_file.write(thumb_response.content)
            except Exception as thumb_err:
                logging.warning(f"Thumbnail download failed: {thumb_err}")
                thumbnail_path = None

        return download.files[0].path, thumbnail_path, video_title

    except Exception as e:
        logging.error(f"Download failed: {str(e)}", exc_info=True)
        
        # Cleanup failed download
        if download and not download.is_removed:
            try:
                download.remove(force=True, files=True)
            except Exception as cleanup_err:
                logging.error(f"Cleanup failed: {cleanup_err}")

        # Prepare fallback links
        buttons = []
        if hd_download_link:
            buttons.append([InlineKeyboardButton("🚀 HD Video", url=hd_download_link)])
        if fast_download_link and fast_download_link != hd_download_link:
            buttons.append([InlineKeyboardButton("⚡ Fast Download", url=fast_download_link)])

        reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
        error_msg = "❌ Download failed. Please try again or use manual links below."

        try:
            await reply_msg.edit_text(error_msg, reply_markup=reply_markup)
        except RPCError:
            pass

        return None, None, None

async def upload_video(client, file_path, thumbnail_path, video_title, reply_msg, collection_channel_id, user_mention, user_id, message):
    try:
        # Validate file existence
        if not os.path.exists(file_path):
            raise FileNotFoundError("Downloaded file not found")

        file_size = os.path.getsize(file_path)
        start_time = datetime.now()
        last_progress_update = time.time()
        uploaded = 0

        async def progress(current, total):
            nonlocal uploaded, last_progress_update
            uploaded = current
            now = time.time()
            
            if now - last_progress_update > 2:
                percentage = (current / total) * 100
                elapsed = (datetime.now() - start_time).total_seconds()
                speed = current / elapsed if elapsed > 0 else 0
                eta = (total - current) / speed if speed > 0 else 0

                progress_text = format_progress_bar(
                    filename=video_title,
                    percentage=percentage,
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
                    last_progress_update = now
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                except RPCError:
                    pass

        # Validate thumbnail
        if not (thumbnail_path and os.path.exists(thumbnail_path)):
            thumbnail_path = None

        # Upload video
        try:
            collection_message = await client.send_video(
                chat_id=collection_channel_id,
                video=file_path,
                caption=f"✨ {video_title}\n👤 ʟᴇᴇᴄʜᴇᴅ ʙʏ : {user_mention}\n📥 ᴜsᴇʀ ʟɪɴᴋ: tg://user?id={user_id}",
                thumb=thumbnail_path,
                progress=progress,
                supports_streaming=True
            )
        except FloodWait as e:
            await asyncio.sleep(e.value)
            collection_message = await client.send_video(...)  # Resend with same parameters

        # Copy to user
        await client.copy_message(
            chat_id=message.chat.id,
            from_chat_id=collection_channel_id,
            message_id=collection_message.id
        )

        # Cleanup
        try:
            await message.delete()
            await reply_msg.delete()
            sticker = await message.reply_sticker("CAACAgIAAxkBAAEZdwRmJhCNfFRnXwR_lVKU1L9F3qzbtAAC4gUAAj-VzApzZV-v3phk4DQE")
            await asyncio.sleep(5)
            await sticker.delete()
        except RPCError:
            pass

        return collection_message.id

    except Exception as e:
        logging.error(f"Upload failed: {str(e)}", exc_info=True)
        error_msg = "❌ Upload failed. Please try again later."
        
        try:
            await reply_msg.edit_text(error_msg)
        except RPCError:
            pass

        return None
    finally:
        # Ensure cleanup of files
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
            if thumbnail_path and os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
        except Exception as cleanup_err:
            logging.error(f"File cleanup failed: {cleanup_err}")
