"""The view_image tool, and a picture's way through a run: into the request,
out of what is printed, and out of the saved chat."""

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from robot import api, chats, history
from robot import tools as tools_module
from robot.tools import ALL_TOOLS, view_image
from tests.fakes import reply, text_block, tool_use
from tests.test_agent import LoopCase

# The first bytes that make a file each kind of picture; the rest is padding.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 300
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 300
GIF = b"GIF89a" + b"\x00" * 300
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 300


class ViewImageCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def file(self, name, content):
        path = self.folder / name
        path.write_bytes(content)
        return path


class TheTool(ViewImageCase):
    def test_a_photo_comes_back_as_a_line_of_text_and_the_picture(self):
        path = self.file("photo.jpg", JPEG)
        note, image = view_image({"path": str(path)})
        self.assertEqual(note, {"type": "text",
                                "text": f"The image {path} (image/jpeg, 304 bytes):"})
        self.assertEqual(image["type"], "image")
        self.assertEqual(image["source"]["type"], "base64")
        self.assertEqual(image["source"]["media_type"], "image/jpeg")
        self.assertEqual(base64.standard_b64decode(image["source"]["data"]), JPEG)
        self.assertNotIn("\n", image["source"]["data"])

    def test_the_kind_of_picture_is_read_from_the_file_not_from_its_name(self):
        for content, wanted in ((JPEG, "image/jpeg"), (PNG, "image/png"), (GIF, "image/gif"),
                                (WEBP, "image/webp")):
            path = self.file("named-wrongly.txt", content)
            self.assertEqual(view_image({"path": str(path)})[1]["source"]["media_type"], wanted)

    def test_a_path_may_start_at_the_home_folder(self):
        self.file("photo.jpg", JPEG)
        with mock.patch.object(tools_module.Path, "home", return_value=self.folder):
            relative = view_image({"path": "photo.jpg"})
        with mock.patch.dict("os.environ", {"HOME": str(self.folder),
                                            "USERPROFILE": str(self.folder)}):
            tilde = view_image({"path": "~/photo.jpg"})
        self.assertEqual(relative[1], tilde[1])

    def test_what_cannot_be_looked_at_is_refused_with_the_reason(self):
        cases = (
            ({}, "'path' must be the path of an image file"),
            ({"path": "   "}, "'path' must be the path of an image file"),
            ({"path": 7}, "'path' must be the path of an image file"),
            ({"path": str(self.folder / "missing.jpg")}, "there is no file at"),
            ({"path": str(self.folder)}, "there is no file at"),
            ({"path": str(self.file("empty.jpg", b""))}, "is empty"),
            ({"path": str(self.file("notes.txt", b"just some text, no picture"))},
             "is not a JPEG, PNG, GIF or WebP image"),
            ({"path": str(self.file("almost.webp", b"RIFF\x24\x00\x00\x00WAVEfmt "))},
             "is not a JPEG, PNG, GIF or WebP image"),
        )
        for tool_input, wanted in cases:
            with self.subTest(tool_input=tool_input):
                with self.assertRaises(ValueError) as caught:
                    view_image(tool_input)
                self.assertIn(wanted, str(caught.exception))

    def test_a_file_too_large_to_send_is_refused(self):
        path = self.file("huge.jpg", JPEG)
        with mock.patch.object(tools_module, "MAX_IMAGE_BYTES", 100):
            with self.assertRaises(ValueError) as caught:
                view_image({"path": str(path)})
        self.assertIn("304 bytes, more than the 100 that can be sent", str(caught.exception))

    def test_the_limit_leaves_room_for_the_encoding(self):
        # base64 makes four characters of every three bytes; the API takes 5 MB.
        self.assertLess(tools_module.MAX_IMAGE_BYTES * 4 / 3, 5 * 1024 * 1024)

    def test_it_is_offered_everywhere_and_may_run_beside_other_tools(self):
        tool = next(tool for tool in ALL_TOOLS if tool.definition["name"] == "view_image")
        self.assertTrue(tool.is_available())
        self.assertTrue(tool.parallel_safe)
        self.assertEqual(tool.definition["input_schema"]["required"], ["path"])


class InARun(LoopCase):
    def setUp(self):
        super().setUp()
        self.photo = Path(self._tmp.name) / "photo.jpg"
        self.photo.write_bytes(JPEG)
        self.tool = next(tool for tool in ALL_TOOLS if tool.definition["name"] == "view_image")

    def run_it(self, path, **flags):
        script = [reply(tool_use("view_image", {"path": str(path)})),
                  reply(text_block("A cabinet with glass doors."))]
        made = self.make(script, tools={"view_image": self.tool})
        for name, value in flags.items():
            setattr(self.console, name, value)
        self.assertEqual(made.run(), "completed")
        return made

    def test_the_picture_goes_to_the_model_as_the_tools_result(self):
        self.run_it(self.photo)
        result = self.client.requests[1]["messages"][-1]["content"][0]
        self.assertEqual(result["type"], "tool_result")
        self.assertNotIn("is_error", result)
        text, image = result["content"]
        self.assertIn(str(self.photo), text["text"])
        self.assertEqual(image["source"]["media_type"], "image/jpeg")
        self.assertEqual(base64.standard_b64decode(image["source"]["data"]), JPEG)

    def test_a_file_that_is_no_picture_is_an_error_the_model_can_read(self):
        other = Path(self._tmp.name) / "notes.txt"
        other.write_text("words", encoding="ascii")
        self.run_it(other)
        result = self.client.requests[1]["messages"][-1]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("is not a JPEG, PNG, GIF or WebP image", result["content"])

    def test_the_encoded_picture_is_not_printed_with_debug_on(self):
        self.run_it(self.photo, debug_on=True)
        shown = self.shown()
        encoded = base64.standard_b64encode(JPEG).decode("ascii")
        self.assertNotIn(encoded[:60], shown)
        self.assertIn(f"<{len(encoded):,} characters of base64 not shown>", shown)
        self.assertIn('"media_type": "image/jpeg"', shown)

    def test_the_saved_chat_holds_a_note_in_place_of_the_picture(self):
        made = self.run_it(self.photo)
        saved = chats.serialize_messages(made.messages)
        self.assertNotIn(base64.standard_b64encode(JPEG).decode("ascii")[:60], json.dumps(saved))
        text, note = saved[2]["content"][0]["content"]
        self.assertIn(str(self.photo), text["text"])       # which picture it was is kept
        self.assertEqual(note, {"type": "text", "text": chats._NESTED_IMAGE_NOTE})

    def test_the_picture_sent_is_not_changed_by_showing_or_saving_it(self):
        made = self.run_it(self.photo, debug_on=True)
        chats.serialize_messages(made.messages)
        image = made.messages[2]["content"][0]["content"][1]
        self.assertEqual(base64.standard_b64decode(image["source"]["data"]), JPEG)


class Sizes(unittest.TestCase):
    def image(self, characters=400_000):
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": "A" * characters}}

    def test_a_picture_in_a_tool_result_counts_as_a_picture_not_by_its_length(self):
        result = {"type": "tool_result", "tool_use_id": "t1",
                  "content": [{"type": "text", "text": "The image:"}, self.image()]}
        estimate = history.estimate_content_tokens([result])
        self.assertLess(estimate, 2000)
        self.assertGreaterEqual(estimate, history._IMAGE_TOKENS)

    def test_a_text_result_is_still_counted_by_its_length(self):
        result = {"type": "tool_result", "tool_use_id": "t1", "content": "x" * 4000}
        self.assertGreater(history.estimate_content_tokens([result]), 1000)

    def test_describing_a_request_leaves_everything_but_picture_data(self):
        messages = [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": [{"type": "text", "text": "The image:"}, self.image(1000)]},
            {"type": "text", "text": "base64 is a word here, and data stays: AAAA"}]}]
        shown = json.loads(api.describe_request({"model": "m", "messages": messages}, []))
        source = shown["messages"][0]["content"][0]["content"][1]["source"]
        self.assertEqual(source, {"type": "base64", "media_type": "image/jpeg",
                                  "data": "<1,000 characters of base64 not shown>"})
        self.assertEqual(shown["messages"][0]["content"][1]["text"],
                         "base64 is a word here, and data stays: AAAA")
        self.assertEqual(len(messages[0]["content"][0]["content"][1]["source"]["data"]), 1000)


if __name__ == "__main__":
    unittest.main()
