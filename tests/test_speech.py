"""Speech in videos: what speech() keeps, and where the narration goes (no network, no model).

    SPEECH_MODEL_TEST=1 python -m unittest tests.test_speech   # also run the real model (downloads it)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy  # noqa: F401  before sys.modules is patched: restoring it would unload numpy, which can't load twice

from worker import pipeline as p
from worker import wiki

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def segment(text, no_speech=0.05, logprob=-0.3):
    return types.SimpleNamespace(text=f" {text}", no_speech_prob=no_speech, avg_logprob=logprob)


class FakeWhisper:
    """faster_whisper.WhisperModel, answering with the segments it was given."""
    segments: list = []
    loaded = 0

    def __init__(self, *args, **kwargs):
        FakeWhisper.loaded += 1

    def transcribe(self, audio, **kwargs):
        assert kwargs["vad_filter"] is True
        return iter(self.segments), types.SimpleNamespace(language="en")


class Speech(unittest.TestCase):
    def setUp(self):
        patches = [mock.patch.object(p, "_whisper", None), mock.patch.object(p, "has_audio", return_value=True),
                   mock.patch.object(p, "video_duration", return_value=30.0),
                   mock.patch.object(p.subprocess, "run", return_value=types.SimpleNamespace(stdout=b"\0\0" * 1600)),
                   mock.patch.dict(sys.modules, {"faster_whisper": types.SimpleNamespace(WhisperModel=FakeWhisper)})]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        FakeWhisper.loaded = 0

    def test_keeps_what_the_model_is_sure_of(self):
        FakeWhisper.segments = [segment("First you open the panel and drag the handle"),
                                segment("Thank you for watching", no_speech=0.9),  # the classic invention
                                segment("garbled", logprob=-1.6),
                                segment("then it snaps into place")]
        self.assertEqual(p.speech(Path("x.mp4")), "First you open the panel and drag the handle then it snaps into place")
        p.speech(Path("y.mp4"))
        self.assertEqual(FakeWhisper.loaded, 1)  # loaded once per process

    def test_a_few_words_are_not_narration(self):
        FakeWhisper.segments = [segment("Yeah."), segment("Oh, nice")]
        self.assertEqual(p.speech(Path("x.mp4")), "")

    def test_a_long_video_says_it_was_cut(self):
        FakeWhisper.segments = [segment("Today I want to talk about how to review an agent's work")]
        with mock.patch.object(p, "video_duration", return_value=1635.0):
            self.assertTrue(p.speech(Path("x.mp4")).endswith("agent's work …"))

    def test_skipped_without_audio_setting_or_library(self):
        FakeWhisper.segments = [segment("Some words that would otherwise be kept here")]
        with mock.patch.object(p, "SPEECH", "off"):
            self.assertEqual(p.speech(Path("x.mp4")), "")
        with mock.patch.object(p, "has_audio", return_value=False):
            self.assertEqual(p.speech(Path("x.mp4")), "")
        with mock.patch.dict(sys.modules, {"faster_whisper": None}):  # not installed
            self.assertEqual(p.speech(Path("x.mp4")), "")
        self.assertEqual(FakeWhisper.loaded, 0)

    def test_a_failure_never_fails_the_capture(self):
        with mock.patch.object(FakeWhisper, "transcribe", side_effect=RuntimeError("out of memory")):
            self.assertEqual(p.speech(Path("x.mp4")), "")


class Narration(unittest.TestCase):
    def test_it_goes_beside_the_frames(self):
        with mock.patch.object(p, "chat", return_value='{"patterns": []}') as chat:
            p.analyze([Path("f.jpg")], "the drag", "post", "Then it snaps into place")
        prompt = chat.call_args.args[1]
        self.assertIn("Post text: post\n\nNarration: Then it snaps into place", prompt)
        self.assertEqual(chat.call_args.kwargs["images"], [Path("f.jpg")])  # the frames still go in

    def test_it_counts_as_words_to_read(self):
        self.assertEqual(p.readable_words({"text": "two words", "speech": "and three more"}), 5)

    def test_the_source_note_keeps_it(self):
        body = wiki.source_body(note=None, text="the post", page=None, patterns=[], style=None,
                                speech="First you open the panel")
        self.assertIn("## Narration\n\nWhat is said in the video, transcribed by a model", body)
        self.assertIn("> First you open the panel", body)
        self.assertNotIn("## Narration", wiki.source_body(note=None, text="x", page=None, patterns=[], style=None))


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class RealAudio(unittest.TestCase):
    def video(self, tmp, audio: str | None) -> Path:
        out = Path(tmp) / "clip.mp4"
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x240:d=4"]
        if audio:
            cmd += ["-f", "lavfi", "-i", audio, "-shortest"]
        subprocess.run([*cmd, "-pix_fmt", "yuv420p", str(out)], check=True)
        return out

    def test_a_silent_video_has_no_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(p.has_audio(self.video(tmp, None)))
            self.assertTrue(p.has_audio(self.video(tmp, "sine=frequency=440:duration=4")))

    @unittest.skipUnless(os.environ.get("SPEECH_MODEL_TEST") == "1", "set SPEECH_MODEL_TEST=1 to run the real model")
    def test_music_gives_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(p, "_whisper", None):
            chord = "sine=frequency=262:duration=4,volume=0.5"
            self.assertEqual(p.speech(self.video(tmp, chord)), "")


if __name__ == "__main__":
    unittest.main()
