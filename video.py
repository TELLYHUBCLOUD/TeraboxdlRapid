import requests
import aria2p
from datetime import datetime
from status import format_progress_bar
import asyncio
import os, time
import logging
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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
    "continue": "true"
}

aria2.set_global_options(options)


async def download_video(url, reply_msg, user_mention, user_id):
    try:
        # Get video metadata from the API
        response = requests.get(f"https://teraboxdl.tellycloudapi.workers.dev/?url={url}")
        response.raise_for_status()
        data = response.json()

        resolutions = data.get("Data", {})
        fast_download_link = resolutions.get("DirectLink")
        hd_download_link = resolutions.get("DirectLink2")
        thumbnail_url = resolutions.get("Thum", [{}])[0].get("360x270")
        video_title = resolutions.get("FileName", "video")

        if not fast_download_link:
            raise ValueError("Fast download link not found in the response.")

        # Start download via aria2
        download = aria2.add_uris([fast_download_link])
        start_time = datetime.now()

        while not download.is_complete:
            download.update()
            percentage = download.progress
            done = download.completed_length
            total_size = download.total_length
            speed = download.download_speed
            eta = download.eta
            elapsed_time_seconds = (datetime.now() - start_time).total_seconds()

            progress_text = format_progress_bar(
                filename=video_title,
                percentage=percentage,
                done=done,
                total_size=total_size,
                status="Downloading",
                eta=eta,
                speed=speed,
                elapsed=elapsed_time_seconds,
                user_mention=user_mention,
                user_id=user_id,
                aria2p_gid=download.gid
            )
            await reply_msg.edit_text(progress_text)
            await asyncio.sleep(2)

        if download.is_complete:
            file_path = download.files[0].path

            # Download thumbnail
            thumbnail_path = "thumbnail.jpg"
            if thumbnail_url:
                thumb_response = requests.get(thumbnail_url)
                thumb_response.raise_for_status()
                with open(thumbnail_path, "wb") as thumb_file:
                    thumb_file.write(thumb_response.content)
            else:
                thumbnail_path = None

            await reply_msg.edit_text("ᴜᴘʟᴏᴀᴅɪɴɢ...")
            return file_path, thumbnail_path, video_title

    except Exception as e:
        logging.error(f"Download failed: {e}")
        buttons = []
        if hd_download_link:
            buttons.append([InlineKeyboardButton("🚀 HD Video", url=hd_download_link)])
        if fast_download_link:
            buttons.append([InlineKeyboardButton("⚡ Fast Download", url=fast_download_link)])

        reply_markup = InlineKeyboardMarkup(buttons) if buttons else None

        await reply_msg.reply_text(
            "Fast Download Link for this video is broken. Please download manually using the link below.",
            reply_markup=reply_markup
        )
        return None, None, None


async def upload_video(client, file_path, thumbnail_path, video_title, reply_msg, collection_channel_id, user_mention, user_id, message):
    try:
        file_size = os.path.getsize(file_path)
        uploaded = 0
        start_time = datetime.now()
        last_update_time = time.time()

        # This will be used for progress updates during the video upload
        async def progress(current, total):
            nonlocal uploaded, last_update_time
            uploaded = current
            percentage = (current / total) * 100
            elapsed_time_seconds = (datetime.now() - start_time).total_seconds()

            # Update progress text every 2 seconds
            if time.time() - last_update_time > 2:
                progress_text = format_progress_bar(
                    filename=video_title,
                    percentage=percentage,
                    done=current,
                    total_size=total,
                    status="Uploading",
                    eta=(total - current) / (current / elapsed_time_seconds) if current > 0 else 0,
                    speed=current / elapsed_time_seconds if current > 0 else 0,
                    elapsed=elapsed_time_seconds,
                    user_mention=user_mention,
                    user_id=user_id,
                    aria2p_gid=""  # No need to provide GID during upload
                )
                try:
                    await reply_msg.edit_text(progress_text)
                    last_update_time = time.time()
                except Exception as e:
                    logging.warning(f"Error updating progress message: {e}")

        # Upload video with the provided progress function
        with open(file_path, 'rb') as file:
            collection_message = await client.send_video(
                chat_id=collection_channel_id,
                video=file,
                caption=f"✨ {video_title}\n👤 ʟᴇᴇᴄʜᴇᴅ ʙʏ : {user_mention}\n📥 ᴜsᴇʀ ʟɪɴᴋ: tg://user?id={user_id}",
                thumb=thumbnail_path,
                progress=progress
            )

            # After uploading, copy the message to the user's chat
            await client.copy_message(
                chat_id=message.chat.id,
                from_chat_id=collection_channel_id,
                message_id=collection_message.id
            )

            # Delete the original message after upload
            await asyncio.sleep(1)
            await message.delete()

        # After everything is done, delete the reply message and send a sticker
        await reply_msg.delete()
        sticker_message = await message.reply_sticker("CAACAgIAAxkBAAEZdwRmJhCNfFRnXwR_lVKU1L9F3qzbtAAC4gUAAj-VzApzZV-v3phk4DQE")

        # Clean up files only after successful upload
        os.remove(file_path)
        os.remove(thumbnail_path)

        # Delay before deleting the sticker message
        await asyncio.sleep(5)
        await sticker_message.delete()

        return collection_message.id

    except Exception as e:
        logging.error(f"Error uploading video: {e}")
        # Handle cleanup and error messaging
        if os.path.exists(file_path):
            os.remove(file_path)
        if os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)
        await reply_msg.edit_text("❌ Failed to upload video. Please try again later.")
        return None
