"""Per-download hint sidecars: the Telegram message text + where to reply.

Keyed by slug == the folder name under /inbox/telegram/<slug>/.
"""
import json
import time

from . import config


def save(slug: str, text: str, chat_id: int, msg_id: int) -> None:
    path = config.HINTS / f"{slug}.json"
    path.write_text(json.dumps({
        "text": text or "",
        "chat_id": chat_id,
        "msg_id": msg_id,
        "created": time.time(),
    }, ensure_ascii=False))


def append_text(slug: str, text: str) -> bool:
    """Add extra context text to an existing hint. False if the hint is gone."""
    path = config.HINTS / f"{slug}.json"
    if not path.is_file() or not text:
        return False
    data = load(slug)
    data["text"] = (data.get("text", "") + "\n" + text).strip()
    path.write_text(json.dumps(data, ensure_ascii=False))
    return True


def load(slug: str) -> dict:
    path = config.HINTS / f"{slug}.json"
    if path.is_file():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def delete(slug: str) -> None:
    (config.HINTS / f"{slug}.json").unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Series memory: manual button answers teach "series name -> ComicVine volume"
# so sibling issues (and future forwards of the same series) skip the question.
# --------------------------------------------------------------------------- #
def _series_map_path():
    return config.DATA / "series_map.json"


def _load_series_map() -> dict:
    try:
        return json.loads(_series_map_path().read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def series_key(name: str) -> str:
    return " ".join((name or "").split()).casefold()


def map_get(name: str) -> dict | None:
    return _load_series_map().get(series_key(name))


def map_set(name: str, volume_id: int, label: str) -> None:
    m = _load_series_map()
    m[series_key(name)] = {"volume_id": volume_id, "label": label}
    _series_map_path().write_text(json.dumps(m, ensure_ascii=False, indent=1))


def map_delete(name: str) -> bool:
    m = _load_series_map()
    k = series_key(name)
    if k not in m:
        return False
    del m[k]
    _series_map_path().write_text(json.dumps(m, ensure_ascii=False, indent=1))
    return True


def map_all() -> dict:
    return _load_series_map()
