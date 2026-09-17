#!/usr/bin/env python3
"""Builds the shareable "Save to second-brain" Shortcut.

    python shortcut/build.py                     # signed shortcut/Save to second-brain.shortcut (macOS)
    python shortcut/build.py --unsigned out.plist  # only the unsigned workflow, to inspect it

Shortcuts only imports signed files and only macOS can sign them (`shortcuts
sign`). The file stores nothing personal: on import, Shortcuts asks for the
Supabase project URL, the publishable key and the capture token.

The workflow is the one the README describes: share a link or text, take its
first URL, ask for an optional note, POST it to the capture() function and show
whether the inbox queued it.
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


def build() -> dict:
    supabase = action("gettext", WFTextActionText=text("https://<project>.supabase.co"))
    key = action("gettext", WFTextActionText=text("sb_publishable_..."))
    token = action("gettext", WFTextActionText=text("<capture token>"))
    # "Get URLs from" reads a text field; a bare variable there is ignored and yields no URL
    urls = action("detect.link", WFInput=text({"Type": "ExtensionInput"}))
    first = action("getitemfromlist", WFInput=attachment(output(urls, "URLs")), WFItemSpecifier="First Item")
    # One tap says what the capture is for; the worker reads it as "intent: …".
    intents = action("list", WFItems=["Pattern to reuse", "Visual style", "Tool to try", "Idea to read", "Idea to grow", "Just save"])
    intent = action("choosefromlist", WFInput=attachment(output(intents, "List")),
                    WFChooseFromListActionPrompt="What caught your eye?")
    # A separate action: "Ask Each Time" inside the JSON body makes Shortcuts ask
    # for the whole dictionary instead of the note alone.
    note = action("ask", WFAskActionPrompt="What do you want from this? For Idea to grow, the thought it gave you (optional)", WFInputType="Text")
    post = action(
        "downloadurl",
        WFURL=text(output(supabase, "Text"), "/rest/v1/rpc/capture"),
        WFHTTPMethod="POST",
        ShowHeaders=True,
        # Supabase reads Authorization as a JWT, so the token travels in the body
        WFHTTPHeaders=dictionary(apikey=text(output(key, "Text"))),
        WFHTTPBodyType="JSON",
        WFJSONValues=dictionary(url=text(output(first, "Item from List")),
                                note=text("intent: ", output(intent, "Chosen Item"), " — ",
                                          output(note, "Provided Input")),
                                token=text(output(token, "Text"))),
    )
    status = action("getvalueforkey", WFInput=attachment(output(post, "Contents of URL")),
                    WFDictionaryKey="status", WFGetDictionaryValueType="Value")
    group = str(uuid.uuid4()).upper()
    actions = [
        supabase, key, token, urls, first, intents, intent, note, post, status,
        action("conditional", GroupingIdentifier=group, WFControlFlowMode=0, WFCondition=4,
               WFConditionalActionString="queued",
               WFInput={"Type": "Variable",
                        "Variable": attachment(output(status, "Dictionary Value", "WFStringContentItem"))}),
        action("notification", WFNotificationActionBody=text("✓ Sent to second-brain")),
        action("conditional", GroupingIdentifier=group, WFControlFlowMode=1),
        action("notification", WFNotificationActionBody=text("✗ Couldn't send: ", output(post, "Contents of URL"))),
        action("conditional", GroupingIdentifier=group, WFControlFlowMode=2),
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
        "WFWorkflowInputContentItemClasses": ["WFURLContentItem", "WFStringContentItem"],  # LinkedIn shares text
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
