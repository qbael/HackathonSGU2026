"""Validate source post assets and prepare input for the Development-only importer.

Each assets/facebook/<source-id>/source.json contains sourceId, sourceUrl,
originalKind (lost/found), capturedAt (ISO timestamp with timezone), sourceText,
title, publicDescription, foundArea, and images (1..3 relative photo filenames).
Only foundDateVerified=true together with foundOn=YYYY-MM-DD sets a verified found date.
An optional scenario object supplies explicitly fictional custody and found time;
source facts and existing imports are never rewritten.

Usage: python3 scripts/import_facebook_samples.py [assets/facebook] --validate
       python3 scripts/import_facebook_samples.py --prepare-json /tmp/findie-public-samples.json
This script only reads local sources and writes the requested prepared JSON.
"""

import argparse
import hashlib
import json
from pathlib import Path
from datetime import date, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from uuid import UUID


SOURCE_HOSTS = {"facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com",
                "mbasic.facebook.com", "timdothatlac.vn", "www.timdothatlac.vn",
                "timdo24h.vn", "www.timdo24h.vn", "timdo24h.com", "www.timdo24h.com"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def text(record, field, maximum):
    value = record.get(field)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{field} must contain 1..{maximum} characters")
    return value.strip()


def scenario_payload(scenario, content):
    if not isinstance(scenario, dict):
        raise ValueError("scenario must be an object")
    if scenario.get("foundTimezone", "Asia/Ho_Chi_Minh") != "Asia/Ho_Chi_Minh":
        raise ValueError("scenario timezone must be Asia/Ho_Chi_Minh")
    precision = scenario.get("foundTimePrecision")
    on, start, end = (scenario.get(key) for key in ("foundOn", "foundFrom", "foundUntil"))
    now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    def timestamp(value):
        if not isinstance(value, str):
            raise ValueError("scenario timestamps must be ISO strings with timezone")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("scenario timestamps must include a timezone")
        return parsed
    valid = False
    if precision == "unknown":
        valid = on is None and start is None and end is None
    elif precision == "date":
        valid = isinstance(on, str) and date.fromisoformat(on) <= now.date() and start is None and end is None
    elif precision == "exact":
        valid = on is None and timestamp(start) <= now and end is None
    elif precision == "range":
        valid = on is None and timestamp(start) <= timestamp(end) <= now
    if not valid:
        raise ValueError("scenario found time is invalid or in the future")
    if on is not None:
        on = date.fromisoformat(on).isoformat()
    if start is not None:
        start = timestamp(start).isoformat()
    if end is not None:
        end = timestamp(end).isoformat()
    content.update(foundTimePrecision=precision)
    for key, value in (("foundOn", on), ("foundFrom", start), ("foundUntil", end)):
        if value is not None:
            content[key] = value
    custody = scenario.get("custody")
    if not isinstance(custody, dict):
        raise ValueError("scenario custody must be an object")
    custody = dict(custody)
    kind = custody.get("kind")
    if kind == "person":
        if set(custody) != {"kind"}:
            raise ValueError("person scenario cannot contain point or external fields")
    elif kind == "point":
        if set(custody) != {"kind", "pointId", "confirmedPhysicalReceipt"} or custody["confirmedPhysicalReceipt"] is not True:
            raise ValueError("point scenario requires a point ID and confirmed physical receipt")
        if not isinstance(custody["pointId"], str) or UUID(custody["pointId"]).int == 0:
            raise ValueError("point scenario requires a nonempty point UUID")
        custody["pointId"] = str(UUID(custody["pointId"]))
    elif kind == "external":
        if set(custody) - {"kind", "name", "address", "instructions"}:
            raise ValueError("external scenario contains unexpected fields")
        text(custody, "name", 200)
        text(custody, "address", 500)
        if "instructions" in custody:
            text(custody, "instructions", 2000)
    else:
        raise ValueError("scenario custody kind must be person, point or external")
    return custody


def prepare(source_path):
    record = json.loads(source_path.read_text(encoding="utf-8"))
    source_id = text(record, "sourceId", 200)
    source_url = text(record, "sourceUrl", 2000)
    parsed = urlsplit(source_url)
    if (parsed.scheme != "https" or parsed.hostname not in SOURCE_HOSTS or parsed.username
            or parsed.password or parsed.port not in (None, 443) or parsed.path in ("", "/")):
        raise ValueError("sourceUrl must be a post on an approved source website")
    if record.get("originalKind") not in ("lost", "found"):
        raise ValueError("originalKind must be lost or found")
    captured = datetime.fromisoformat(text(record, "capturedAt", 100).replace("Z", "+00:00"))
    if captured.tzinfo is None or captured > datetime.now(captured.tzinfo):
        raise ValueError("capturedAt must include a timezone and cannot be in the future")
    text(record, "sourceText", 50000)
    description = text(record, "publicDescription", 5000)
    original_kind = "báo mất" if record["originalKind"] == "lost" else "nhặt được / tìm chủ"
    disclosure = ("DỮ LIỆU MẪU từ bài đăng nguồn; ứng dụng không giữ món đồ và chưa xác nhận tình trạng hiện tại. "
                  f"Bài gốc: {original_kind}. ")
    if record["originalKind"] == "lost":
        disclosure += "Chuyển thể để thử nghiệm luồng nhặt đồ; vị trí là khu vực báo mất, chưa xác nhận đã nhặt được. "
    scenario = record.get("scenario")
    if scenario is not None:
        disclosure = ("DỮ LIỆU MẪU — KỊCH BẢN GIẢ ĐỊNH dựa trên bài đăng nguồn. "
                      f"Bài gốc: {original_kind}. "
                      "Người giữ, Hub, nơi ngoài hệ thống và ngày giờ trong kịch bản chỉ phục vụ kiểm thử; "
                      "không xác nhận đã nhặt được, bàn giao hay tình trạng hiện tại của đồ thật.")
    description += f"\n\n{disclosure}\nNguồn: {source_url}"
    if len(description) > 5000:
        raise ValueError("publicDescription plus source disclosure exceeds 5000 characters")
    title = text(record, "title", 200)
    content = {"title": title, "publicDescription": description,
               "foundArea": text(record, "foundArea", 200), "foundTimePrecision": "unknown",
               "foundTimezone": "Asia/Ho_Chi_Minh"}
    if record.get("foundDateVerified") is True:
        if record["originalKind"] != "found":
            raise ValueError("a lost post cannot establish a verified found date")
        found_on = date.fromisoformat(text(record, "foundOn", 10))
        if found_on > datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date():
            raise ValueError("foundOn cannot be in the future")
        content.update(foundTimePrecision="date", foundOn=found_on.isoformat())
    image_names = record.get("images")
    if not isinstance(image_names, list) or not 1 <= len(image_names) <= 3:
        raise ValueError("images must list 1..3 actual local photos")
    photos = []
    for name in image_names:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("each image must be a relative local filename")
        photo = (source_path.parent / name).resolve()
        if Path(name).is_absolute() or not photo.is_relative_to(source_path.parent.resolve()) or not photo.is_file():
            raise ValueError("image is missing or outside its source folder")
        if not 0 < photo.stat().st_size <= MAX_IMAGE_BYTES:
            raise ValueError("each photo must be nonempty and at most 10 MiB")
        raw = photo.read_bytes()
        mime = ("image/jpeg" if raw.startswith(b"\xff\xd8\xff") else
                "image/png" if raw.startswith(b"\x89PNG\r\n\x1a\n") else
                "image/webp" if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP" else None)
        if mime is None:
            raise ValueError("photo must be JPEG, PNG or WebP")
        photos.append({"path": photo, "mime": mime, "sha256": hashlib.sha256(raw).hexdigest()})
    if len({photo["sha256"] for photo in photos}) != len(photos):
        raise ValueError("duplicate photos within one post")
    instructions = f"Chưa xác nhận người đang giữ hoặc địa điểm bàn giao. Nguồn: {source_url}"
    if len(instructions) > 2000:
        raise ValueError("source URL makes custody instructions exceed 2000 characters")
    payload = {"content": content, "custody": {"kind": "external", "name": "Nguồn bài đăng — dữ liệu mẫu",
               "address": "Ứng dụng không lưu giữ món đồ; xem bài đăng gốc.",
               "instructions": instructions}}
    def fingerprint(value):
        return hashlib.sha256(json.dumps({"source": record, "payload": value,
            "photos": [photo["sha256"] for photo in photos]}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if scenario is not None:
        if record.get("foundDateVerified") is True:
            raise ValueError("scenario dates cannot be marked as verified source dates")
        payload["custody"] = scenario_payload(scenario, content)
    legacy_payload = payload | {"content": content | {"title": "[Mẫu] " + title}}
    return {"sourceId": source_id, "sourceUrl": source_url, "path": source_path,
            "payload": payload, "photos": photos, "fingerprint": fingerprint(payload),
            "legacyTitleFingerprint": fingerprint(legacy_payload),
            **({"syntheticScenario": True} if scenario is not None else {})}


def load_dataset(folder):
    paths = sorted(folder.rglob("source.json"))
    if not paths:
        raise ValueError("no source.json files found")
    posts = [prepare(path) for path in paths]
    for key in ("sourceId", "sourceUrl"):
        if len({post[key] for post in posts}) != len(posts):
            raise ValueError(f"duplicate {key} in dataset")
    return posts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path, nargs="?", default=Path("assets/facebook"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate", action="store_true", help="validate local assets only (default)")
    mode.add_argument("--prepare-json", type=Path, help="write validated input for the Development-only service importer")
    args = parser.parse_args()
    posts = load_dataset(args.folder)
    print(f"Validated {len(posts)} distinct source manifests and {sum(len(post['photos']) for post in posts)} local photos.", flush=True)
    if args.prepare_json:
        args.prepare_json.write_text(json.dumps(posts, default=lambda value: str(value.resolve()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        raise SystemExit(str(error)) from None
