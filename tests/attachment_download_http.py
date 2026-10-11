#!/usr/bin/env python3
"""Native media/download regression against an explicitly marked synthetic server.

Start the backend with a nonempty RG_SUPPORTED_CLIENT_CONTRACTS and two verified
fixture accounts from tools/integration.py. This test creates synthetic records;
it never starts/stops a server, changes configuration, or deletes stored data.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "tools"))
from integration import Client, EMAIL, SECOND, PASSWORD, require, uid


def login(origin: str, contract: str, email: str) -> Client:
    client = Client(origin, email=email)
    client.contract = contract
    client.csrf = client.json("GET", "/api/v1/session")["csrfToken"]
    result = client.json("POST", "/api/v1/session/login", {"email": email, "password": PASSWORD})
    client.csrf, client.owner = result["csrfToken"], result["user"]["id"]
    return client


def native(client: Client) -> Client:
    """Cookie-only client, like img/audio/video and an ordinary download anchor."""
    result = Client(client.origin, email=client.email)
    result.cookie = client.cookie
    require(result.owner is None and result.contract is None, "Native fixture must omit custom client/account headers.")
    return result


def error_code(client: Client, method: str, path: str, code: str, status: int = 409, **options) -> None:
    body, _ = client.request(method, path, expected=status, **options)
    if method != "HEAD":
        require(json.loads(body).get("error", {}).get("code") == code, "Unexpected error code for " + method + " " + path)
    else:
        require(not body, "HEAD error response must have no body.")


def upload(owner: Client, path: str, node: str, name: str, hint: str, data: bytes) -> str:
    ticket = owner.json("POST", path + "/uploads", {
        "idempotencyKey": uid(), "originalName": name, "expectedMimeType": hint,
        "expectedByteSize": len(data),
    }, expected=201)
    complete = owner.json("PUT", path + "/uploads/" + ticket["id"] + "/content", raw=data,
                          headers={"Content-Type": "application/octet-stream"})
    require(complete["state"] == "completed" and complete["sha256"] == hashlib.sha256(data).hexdigest(), "Upload content/hash was not confirmed.")
    asset = uid()
    owner.commands(path, [
        {"kind": "asset.register", "uploadId": ticket["id"], "assetId": asset,
         "metadata": {"title": name, "sourceUrl": None, "sourceAuthor": None,
                      "sourceCreatedAt": None, "noteMarkdown": "Synthetic native download regression"}},
        {"kind": "attachment.attach", "attachment": {"id": uid(), "nodeId": node, "assetId": asset,
         "role": "attachment", "caption": None, "sortOrder": 0}},
    ])
    return asset


def check_download(client: Client, path: str, data: bytes, mime: str, attachment: bool) -> None:
    body, headers = client.request("GET", path)
    require(body == data, "Native GET changed the original bytes.")
    require(headers.get("content-type", "").split(";", 1)[0] == mime, "Native GET MIME mismatch.")
    require(headers.get("x-content-type-options") == "nosniff", "Native original is missing nosniff.")
    require(headers.get("cache-control") == "no-store", "Native original must not be cached across account changes.")
    require(int(headers.get("content-length", "-1")) == len(data), "Native GET length mismatch.")
    require(headers.get("etag") == '"' + hashlib.sha256(data).hexdigest() + '"', "Native original hash mismatch.")
    if attachment:
        require(headers.get("content-disposition", "").startswith("attachment;"), "Arbitrary original must always download.")
    head, head_headers = client.request("HEAD", path)
    require(not head and int(head_headers.get("content-length", "-1")) == len(data), "Native HEAD lost the original size.")
    require(head_headers.get("content-type") == headers.get("content-type"), "Native HEAD MIME differs from GET.")
    if data:
        end = min(len(data) - 1, 15)
        part, part_headers = client.request("GET", path, headers={"Range": f"bytes=0-{end}"}, expected=206)
        require(part == data[:end + 1], "Native Range changed original bytes.")
        require(part_headers.get("content-range") == f"bytes 0-{end}/{len(data)}", "Native Range metadata is incorrect.")


def run(origin: str, contract: str) -> dict:
    owner, foreign = login(origin, contract, EMAIL), login(origin, contract, SECOND)
    owner_native, foreign_native, anonymous = native(owner), native(foreign), Client(origin)
    require(owner.owner != foreign.owner, "Fixture accounts must be distinct.")
    # This fails if the server is accidentally run without production contract gating.
    error_code(owner_native, "GET", "/api/v1/capabilities", "account_changed")
    owner.json("GET", "/api/v1/capabilities")
    investigation = owner.create("Synthetic native download regression " + uid())
    path = "/api/v1/investigations/" + investigation["id"]
    graph = owner.json("GET", path + "/graph")
    node_type = next(item["id"] for item in graph["nodeTypes"] if item["code"] == "note")
    node = uid()
    owner.commands(path, [{"kind": "node.create", "node": {"id": node, "typeId": node_type,
        "title": "Synthetic originals", "bodyMarkdown": "Keep all uploaded original bytes."}, "position": {"x": 0, "y": 0}}])
    fixture_root = ROOT / "tests/fixtures/media"
    cases = [(name, mime, (fixture_root / name).read_bytes()) for name, mime in [
        ("synthetic.png", "image/png"), ("synthetic.jpg", "image/jpeg"),
        ("synthetic.wav", "audio/wav"), ("synthetic.mp4", "video/mp4"),
    ]]
    cases += [("Кириллица <html>.html", "application/octet-stream", b"<html><script>alert(1)</script></html>"),
              ("synthetic.pdf", "application/pdf", b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"),
              ("empty.bin", "application/octet-stream", b"")]
    originals = {}
    for name, mime, data in cases:
        asset = upload(owner, path, node, name, mime, data)
        content = path + "/assets/" + asset + "/content"
        originals[asset] = (data, mime)
        check_download(owner_native, content, data, mime, mime.startswith("application/"))
        if mime.startswith("application/"):
            _, forced = owner_native.request("GET", content + "?download=false")
            require(forced.get("content-disposition", "").startswith("attachment;"), "download=false bypassed inert file delivery.")
            metadata = owner.json("GET", path + "/assets/" + asset)
            require(metadata["previewAllowed"] is False, "Generic/PDF original must not activate preview.")
        for method in ["GET", "HEAD"]:
            error_code(owner_native, method, content, "account_changed", headers={"X-TraceWeave-Account-ID": foreign.owner})
            error_code(foreign_native, method, content, "not_found", status=404)
            error_code(anonymous, method, content, "unauthenticated", status=401)
        error_code(owner_native, "GET", path + "/assets/" + asset, "account_changed")
        error_code(owner_native, "OPTIONS", content, "account_changed")
        error_code(owner_native, "POST", content, "account_changed", headers={
            "X-CSRF-Token": owner.csrf, "X-TraceWeave-Client-Contract": contract})

    # Re-adding the same file creates independent document records.
    duplicate_data = cases[4][2]
    duplicate = upload(owner, path, node, cases[4][0], "application/octet-stream", duplicate_data)
    originals[duplicate] = (duplicate_data, "application/octet-stream")
    document = owner.json("GET", path + "/nodes/" + node)
    require(len(document["attachments"]) == len(originals), "Repeated upload collapsed independent attachments.")
    require({asset["id"] for asset in document["assets"]} == set(originals), "Document lost an uploaded original.")
    before = document
    failed = owner.json("POST", path + "/uploads", {"idempotencyKey": uid(), "originalName": "interrupted.bin",
        "expectedMimeType": "application/octet-stream", "expectedByteSize": 4}, expected=201)
    error_code(owner, "PUT", path + "/uploads/" + failed["id"] + "/content", "validation_failed", status=422,
               raw=b"abc", headers={"Content-Type": "application/octet-stream"})
    rejected_asset = uid()
    error_code(owner, "POST", path + "/commands", "job_not_ready", value={"operationId": uid(), "clientId": uid(),
        "baseRevision": before["revision"], "commands": [{"kind": "asset.register", "uploadId": failed["id"],
        "assetId": rejected_asset, "metadata": {"title": "Must not exist", "sourceUrl": None,
        "sourceAuthor": None, "sourceCreatedAt": None, "noteMarkdown": ""}}]})
    require(owner.json("GET", path + "/nodes/" + node) == before, "Failed upload changed the saved document.")
    error_code(owner, "GET", path + "/assets/" + rejected_asset, "not_found", status=404)

    job = owner.json("POST", path + "/exports", {"idempotencyKey": uid(), "kind": "obsidian_vault",
        "sourceRevision": before["revision"]}, expected=202)
    export_path = path + "/exports/" + job["id"]
    deadline = time.monotonic() + 60
    while job["state"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.1)
        job = owner.json("GET", export_path)
    require(job["state"] == "succeeded", "Synthetic export did not complete.")
    download = export_path + "/download"
    archive_bytes, headers = owner_native.request("GET", download)
    require(hashlib.sha256(archive_bytes).hexdigest() == job["sha256"], "Native ZIP hash differs from its job.")
    require(headers.get("content-disposition", "").startswith("attachment;"), "Native export must download.")
    head, head_headers = owner_native.request("HEAD", download)
    require(not head and int(head_headers["content-length"]) == len(archive_bytes), "Native export HEAD size mismatch.")
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        files = json.loads(archive.read("metadata/files.json"))
        for asset, (data, _) in originals.items():
            require(archive.read(files["assets"][asset]) == data, "Raw export changed an original.")
    for method in ["GET", "HEAD"]:
        error_code(owner_native, method, download, "account_changed", headers={"X-TraceWeave-Account-ID": foreign.owner})
        error_code(foreign_native, method, download, "not_found", status=404)
        error_code(anonymous, method, download, "unauthenticated", status=401)
    error_code(owner_native, "GET", export_path, "account_changed")
    error_code(owner_native, "OPTIONS", download, "account_changed")
    error_code(owner_native, "GET", path + "/graph", "account_changed")
    return {"status": "passed", "checks": ["production account fencing enabled", "native media GET/HEAD/Range",
        "native ZIP GET/HEAD", "PNG/JPEG/audio/video original bytes", "generic/PDF forced downloads", "empty original",
        "repeated file creates independent attachment", "failed upload has no asset or attachment",
        "explicit wrong account rejected", "anonymous rejected", "foreign owner rejected",
        "JSON and mutation fencing retained", "OPTIONS is not exempt", "raw export preserves every original"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--fixture-marker", type=Path, required=True)
    parser.add_argument("--report-out", type=Path)
    args = parser.parse_args()
    require(re.fullmatch(r"[a-f0-9]{64}", args.contract) is not None, "Supply the server's synthetic supported contract hash.")
    require(args.fixture_marker.is_file() and json.loads(args.fixture_marker.read_text()) == {"synthetic": True, "email": EMAIL},
            "Refusing to run without the exact synthetic installation marker.")
    result = run(args.origin, args.contract)
    if args.report_out:
        with args.report_out.open("x", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
            output.write("\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
