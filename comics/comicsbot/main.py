"""comics-bot entrypoint: Telegram client, authorization, background processor."""
import asyncio
import json
import logging

from telethon import TelegramClient, events

from . import config, ingest, processor

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("telethon").setLevel(logging.WARNING)
log = logging.getLogger("comicsbot")

OWNER_FILE = config.DATA / "owner.json"


def get_owner() -> int:
    if config.OWNER_ID:
        return config.OWNER_ID
    if OWNER_FILE.is_file():
        try:
            return int(json.loads(OWNER_FILE.read_text()).get("owner_id", 0))
        except (json.JSONDecodeError, ValueError, OSError):
            pass
    return 0


def set_owner(user_id: int) -> None:
    OWNER_FILE.write_text(json.dumps({"owner_id": user_id}))
    log.info("owner set to %s", user_id)


def _authorized(event) -> bool:
    """Private chats: owner only (first /start claims ownership).
    Groups/channels: allowed — the bot only receives messages where it was
    deliberately added (as admin, for channels)."""
    if not event.is_private:
        return True
    owner = get_owner()
    if owner == 0 and (event.raw_text or "").strip().startswith("/start"):
        set_owner(event.sender_id)
        return True
    return event.sender_id == owner


async def amain() -> None:
    config.ensure_dirs()
    client = TelegramClient(str(config.DATA / "bot"), config.API_ID, config.API_HASH)
    await client.start(bot_token=config.BOT_TOKEN)

    @client.on(events.NewMessage(incoming=True))
    async def on_message(event):
        if event.message.out:
            return
        if not _authorized(event):
            if event.is_private:
                await event.reply("Not authorized. This is a personal bot.")
            return
        try:
            await ingest.handle_message(event)
        except Exception:  # noqa: BLE001
            log.exception("message handling failed")
            try:
                await event.reply("❌ Something went wrong handling that message (see logs).")
            except Exception:  # noqa: BLE001
                pass

    @client.on(events.CallbackQuery())
    async def on_callback(event):
        owner = get_owner()
        if owner and event.sender_id and event.sender_id != owner:
            await event.answer("Not authorized.")
            return
        try:
            await processor.handle_callback(event)
        except Exception:  # noqa: BLE001
            log.exception("callback handling failed")
            await event.answer("Error (see logs).")

    asyncio.ensure_future(processor.loop(client))
    me = await client.get_me()
    log.info("comics-bot running as @%s", me.username)
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(amain())
