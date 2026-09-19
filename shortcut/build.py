#!/usr/bin/env python3
"""Builds the shareable "Save to second-brain" Shortcut.

    python shortcut/build.py                     # signed shortcut/Save to second-brain.shortcut (macOS)
    python shortcut/build.py --unsigned out.plist  # only the unsigned workflow, to inspect it

Shortcuts only imports signed files and only macOS can sign them (`shortcuts
sign`). The file stores nothing personal: on import, Shortcuts asks for the
Supabase project URL, the publishable key and the capture token.

The workflow is the one the README describes: share a link, text or an image;
if an image was shared it's converted to JPEG and base64-encoded and POSTed to
capture_image(), otherwise the first URL goes to capture(); either way it asks
for an optional note and shows whether the inbox queued it.
"""
from __future__ import annotations

import argparse
import plistlib
import subprocess
import tempfile
import uuid
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent / "Save to second-brain.shortcut"
OBJECT = "￼"  # where a variable sits inside a text field


def action(identifier: str, **params) -> dict:
    return {"WFWorkflowActionIdentifier": f"is.workflow.actions.{identifier}",
            "WFWorkflowActionParameters": {"UUID": str(uuid.uuid4()).upper(), **params}}


def output(source: dict, name: str, coerce_to: str | None = None) -> dict:
    """A reference to what an earlier action returned."""
    ref = {"Type": "ActionOutput", "OutputName": name,
           "OutputUUID": source["WFWorkflowActionParameters"]["UUID"]}
    if coerce_to:
        ref["Aggrandizements"] = [{"Type": "WFCoercionVariableAggrandizement", "CoercionItemClass": coerce_to}]
    return ref


def attachment(ref: dict) -> dict:
    return {"Value": ref, "WFSerializationType": "WFTextTokenAttachment"}


def text(*parts: str | dict) -> dict:
    """A text field made of plain strings and variable references, in order.
    Ranges count UTF-16 code units, as Shortcuts does."""
    string, attachments = "", {}
    for part in parts:
        if isinstance(part, str):
            string += part
        else:
            attachments[f"{{{len(string.encode('utf-16-le')) // 2}, 1}}"] = part
            string += OBJECT
    return {"Value": {"string": string, "attachmentsByRange": attachments},
            "WFSerializationType": "WFTextTokenString"}


def dictionary(**items: dict) -> dict:
    return {"Value": {"WFDictionaryFieldValueItems": [
                {"WFItemType": 0, "WFKey": text(key), "WFValue": value} for key, value in items.items()]},
            "WFSerializationType": "WFDictionaryFieldValue"}


def status_block(post: dict, ok_message: str) -> list[dict]:
    """After a capture POST: read `status` and show ✓/✗. The same check for both
    branches, so a URL and an image are confirmed the same way."""
    status = action("getvalueforkey", WFInput=attachment(output(post, "Contents of URL")),
                    WFDictionaryKey="status", WFGetDictionaryValueType="Value")
    group = str(uuid.uuid4()).upper()
    return [
        status,
        action("conditional", GroupingIdentifier=group, WFControlFlowMode=0, WFCondition=4,
               WFConditionalActionString="queued",
               WFInput={"Type": "Variable",
                        "Variable": attachment(output(status, "Dictionary Value", "WFStringContentItem"))}),
        action("notification", WFNotificationActionBody=text(ok_message)),
        action("conditional", GroupingIdentifier=group, WFControlFlowMode=1),
        action("notification", WFNotificationActionBody=text("✗ Couldn't send: ", output(post, "Contents of URL"))),
        action("conditional", GroupingIdentifier=group, WFControlFlowMode=2),
    ]


def build() -> dict:
    supabase = action("gettext", WFTextActionText=text("https://<project>.supabase.co"))
    key = action("gettext", WFTextActionText=text("sb_publishable_..."))
    token = action("gettext", WFTextActionText=text("<capture token>"))
    # detect.link extracts the URL from a shared link (Safari, Chrome or an app that
    # shares text). Its first item decides the branch: a URL means a link/text was
    # shared, an empty value means a screenshot or photo. (count returned 0 even on a
    # non-empty list, so the branch tests the first URL directly instead.)
    urls = action("detect.link", WFInput=text({"Type": "ExtensionInput"}))
    first = action("getitemfromlist", WFInput=attachment(output(urls, "URLs")), WFItemSpecifier="First Item")
    # Comparing the first URL to an empty string is unreliable (an empty list item
    # doesn't test equal to ""), so append a sentinel: an empty first yields exactly
    # the sentinel (a photo), a URL yields url+sentinel (a link), and both compare
    # with the plain "Is" test that the status check already uses.
    marker = action("gettext", WFTextActionText=text(output(first, "Item from List"), "SBNOURL"))
    # One tap says what the capture is for; the worker reads it as "intent: …".
    intents = action("list", WFItems=["Pattern to reuse", "Visual style", "Tool to try", "Idea to read", "Idea to grow", "Just save"])
    intent = action("choosefromlist", WFInput=attachment(output(intents, "List")),
                    WFChooseFromListActionPrompt="What caught your eye?")
    # A separate action: "Ask Each Time" inside the JSON body makes Shortcuts ask
    # for the whole dictionary instead of the note alone.
    note = action("ask", WFAskActionPrompt="What do you want from this? For Idea to grow, the thought it gave you (optional)", WFInputType="Text")

    def note_body():  # rebuilt per branch: it references the intent and note outputs
        return text("intent: ", output(intent, "Chosen Item"), " — ", output(note, "Provided Input"))

    def headers():  # Supabase reads Authorization as a JWT, so the token travels in the body
        return dictionary(apikey=text(output(key, "Text")))

    # Image branch: the first shared item is the image; convert it to JPEG and base64.
    firstimg = action("getitemfromlist", WFInput=attachment({"Type": "ExtensionInput"}), WFItemSpecifier="First Item")
    jpg = action("image.convert", WFInput=attachment(output(firstimg, "Item from List")),
                 WFImageFormat="JPEG", WFImageCompressionQuality=0.8)
    b64 = action("base64encode", WFInput=attachment(output(jpg, "Converted Image")), WFEncodeMode="Encode")
    post_img = action(
        "downloadurl",
        WFURL=text(output(supabase, "Text"), "/rest/v1/rpc/capture_image"),
        WFHTTPMethod="POST", ShowHeaders=True, WFHTTPHeaders=headers(), WFHTTPBodyType="JSON",
        WFJSONValues=dictionary(image=text(output(b64, "Base64 Encoded")), mime=text("image/jpeg"),
                                note=note_body(), token=text(output(token, "Text"))),
    )

    # URL branch: the shared URL (already resolved as `first`).
    post_url = action(
        "downloadurl",
        WFURL=text(output(supabase, "Text"), "/rest/v1/rpc/capture"),
        WFHTTPMethod="POST", ShowHeaders=True, WFHTTPHeaders=headers(), WFHTTPBodyType="JSON",
        WFJSONValues=dictionary(url=text(output(first, "Item from List")), note=note_body(),
                                token=text(output(token, "Text"))),
    )

    outer = str(uuid.uuid4()).upper()
    actions = [
        supabase, key, token, urls, first, marker, intents, intent, note,
        # marker is just the sentinel when no URL was shared (a screenshot or photo);
        # otherwise it's the URL followed by the sentinel (a link or text).
        action("conditional", GroupingIdentifier=outer, WFControlFlowMode=0, WFCondition=4,
               WFConditionalActionString="SBNOURL",
               WFInput={"Type": "Variable",
                        "Variable": attachment(output(marker, "Text", "WFStringContentItem"))}),
        firstimg, jpg, b64, post_img, *status_block(post_img, "✓ Image sent to second-brain"),
        action("conditional", GroupingIdentifier=outer, WFControlFlowMode=1),  # Otherwise: a link or text
        post_url, *status_block(post_url, "✓ Sent to second-brain"),
        action("conditional", GroupingIdentifier=outer, WFControlFlowMode=2),
    ]
    questions = [
        ("https://<project>.supabase.co", "Your Supabase project URL, like https://abcd1234.supabase.co"),
        ("sb_publishable_...", "Your Supabase publishable key (starts with sb_publishable_)"),
        ("<capture token>", "Your capture token: the INBOX_TOKEN whose sha256 you registered in Supabase"),
    ]
    return {
        "WFWorkflowClientVersion": "2605.0.5",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {"WFWorkflowIconStartColor": 4282601983, "WFWorkflowIconGlyphNumber": 59511},
        "WFWorkflowTypes": ["ActionExtension"],  # the share sheet, on iPhone and Mac
        # LinkedIn shares text; a screenshot or photo shares an image
        "WFWorkflowInputContentItemClasses": ["WFURLContentItem", "WFStringContentItem", "WFImageContentItem"],
        "WFWorkflowHasShortcutInputVariables": True,
        "WFWorkflowOutputContentItemClasses": [],
        "WFQuickActionSurfaces": [],
        "WFWorkflowImportQuestions": [
            {"ActionIndex": i, "Category": "Parameter", "ParameterKey": "WFTextActionText",
             "DefaultValue": default, "Text": prompt}
            for i, (default, prompt) in enumerate(questions)],
        "WFWorkflowActions": actions,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--unsigned", type=Path, help="write the unsigned workflow here and stop")
    args = ap.parse_args()
    workflow = plistlib.dumps(build(), fmt=plistlib.FMT_BINARY)
    if args.unsigned:
        args.unsigned.write_bytes(workflow)
        print(args.unsigned)
        return
    with tempfile.TemporaryDirectory() as tmp:
        unsigned = Path(tmp) / "unsigned.shortcut"
        unsigned.write_bytes(workflow)
        subprocess.run(["shortcuts", "sign", "--mode", "anyone", "--input", str(unsigned), "--output", str(OUTPUT)],
                       check=True)
    print(OUTPUT)


if __name__ == "__main__":
    main()
