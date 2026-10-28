import base64
import hashlib
import json
import os
import re
import urllib.request
import uuid

def stop(message):
    raise SystemExit(message)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def send(pdf, filename):
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        stop("Repeated attempts are blocked. Check the channel before starting another delivery.")
    owner_text = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not re.fullmatch(r"[1-9][0-9]*", owner_text):
        stop("Existing owner private-chat configuration is missing or malformed.")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_text = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        stop("TELEGRAM_BOT_TOKEN is missing or malformed.")
    if not re.fullmatch(r"-[1-9][0-9]*", chat_text):
        stop("TELEGRAM_CHANNEL_ID must contain the negative numeric channel ID, not an invite link.")
    chat_id = int(chat_text)
    pdf_sha256 = hashlib.sha256(pdf).hexdigest()
    if not pdf.startswith(b"%PDF-") or not pdf:
        stop("The embedded test PDF failed its integrity check.")
    opener = urllib.request.build_opener(NoRedirect())

    def api(method, parameters=None, body=None, content_type="application/json"):
        if body is None:
            body = json.dumps(parameters or {}).encode("utf-8")
        request = urllib.request.Request(
            "https://api.telegram.org/bot" + token + "/" + method,
            data=body, headers={"Content-Type": content_type}, method="POST",
        )
        try:
            with opener.open(request, timeout=30) as response:
                payload = json.load(response)
        except Exception:
            if method == "sendDocument":
                stop("Upload result is uncertain. Check Telegram before rerunning; no automatic retry was attempted.")
            stop("Telegram request failed. Sensitive URLs, responses and exception details are suppressed.")
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            stop("Telegram rejected a request. Sensitive response details are suppressed.")
        return payload.get("result")

    bot = api("getMe")
    if (not isinstance(bot, dict) or bot.get("is_bot") is not True
            or not isinstance(bot.get("username"), str)
            or bot["username"].lower() != "nsemorningreportbot"
            or type(bot.get("id")) is not int):
        stop("The saved token does not belong to @NSEMorningReportbot.")
    chat = api("getChat", {"chat_id": chat_id})
    if (not isinstance(chat, dict) or chat.get("type") != "channel"
            or type(chat.get("id")) is not int or chat["id"] != chat_id):
        stop("The saved chat ID did not resolve to the expected channel.")

    if chat.get("title") != "NSE Morning Report":
        stop("Channel title differs from the channel verified during setup. Review the destination before sending.")
    member = api("getChatMember", {"chat_id": chat_id, "user_id": bot["id"]})
    owner = api("getChatMember", {"chat_id": chat_id, "user_id": int(owner_text)})
    if (not isinstance(member, dict) or not isinstance(member.get("user"), dict)
            or member["user"].get("id") != bot["id"]
            or member.get("status") != "administrator" or member.get("can_post_messages") is not True):
        stop("Bot posting permission in the channel was not confirmed.")
    if (not isinstance(owner, dict) or not isinstance(owner.get("user"), dict)
            or owner["user"].get("id") != int(owner_text) or owner.get("status") != "creator"):
        stop("Channel ownership does not match the configured private-chat user.")

    boundary = "nse_pdf_" + uuid.uuid4().hex
    chunks = []
    for name, value in [
        ("chat_id", chat_text),
        ("caption", "NSE Morning Report - PARTIAL TRIAL. Check missing signals, data timestamps and limitations in the PDF."),
    ]:
        chunks.append((
            "--" + boundary + "\r\n"
            + 'Content-Disposition: form-data; name="' + name + '"\r\n\r\n'
            + value + "\r\n"
        ).encode("utf-8"))
    chunks.append((
        "--" + boundary + "\r\n"
        + 'Content-Disposition: form-data; name="document"; filename="' + filename + '"\r\n'
        + "Content-Type: application/pdf\r\n\r\n"
    ).encode("ascii"))
    chunks.extend([pdf, ("\r\n--" + boundary + "--\r\n").encode("ascii")])
    sent = api("sendDocument", body=b"".join(chunks),
               content_type="multipart/form-data; boundary=" + boundary)
    if not isinstance(sent, dict):
        stop("The PDF upload did not return a valid message. Check Telegram before rerunning.")
    sent_chat = sent.get("chat")
    document = sent.get("document")
    if (not isinstance(sent_chat, dict) or sent_chat.get("id") != chat_id
            or sent_chat.get("type") != "channel"
            or not isinstance(document, dict)
            or not isinstance(document.get("file_id"), str) or not document["file_id"]
            or type(sent.get("message_id")) is not int or sent["message_id"] <= 0):
        stop("The upload response did not confirm a document in the expected channel. Check Telegram before rerunning.")

    file = api("getFile", {"file_id": document["file_id"]})
    path = file.get("file_path") if isinstance(file, dict) else None
    if (not isinstance(path, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", path)
            or path.startswith("/") or ".." in path.split("/")):
        stop("Telegram accepted the upload but file verification could not proceed. Check Telegram before rerunning.")
    try:
        request = urllib.request.Request("https://api.telegram.org/file/bot" + token + "/" + path)
        with opener.open(request, timeout=30) as response:
            downloaded = response.read(len(pdf) + 1)
    except Exception:
        stop("Telegram accepted the PDF but the verification download failed. Check Telegram before rerunning.")
    if hashlib.sha256(downloaded).hexdigest() != pdf_sha256:
        stop("Telegram accepted a document but the downloaded bytes did not match the test PDF.")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
        summary.write("## Telegram channel delivery verified\n\n")
        summary.write("Telegram accepted the PDF in the configured channel.\n\n")
        summary.write("The downloaded copy matches the original PDF by SHA-256.\n\n")
        summary.write("Partial-trial PDF delivered; missing data and unresolved source validation remain labelled.\n")
    print("CHANNEL_DELIVERY_RESULT: PDF accepted in verified channel; downloaded SHA-256 matches original.")

    return {"status": "SENT", "pdf_sha256": pdf_sha256}
