import io
import unittest
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.api.routes.transcripts import read_audio_upload


def upload(content: bytes, filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        io.BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


class UploadValidationTests(unittest.TestCase):
    def test_valid_audio_is_read(self):
        file = upload(b"RIFF-data", "meeting.wav", "audio/wav")

        self.assertEqual(read_audio_upload(file), b"RIFF-data")

    def test_unsupported_file_type_is_rejected(self):
        file = upload(b"text", "meeting.txt", "text/plain")

        with self.assertRaises(HTTPException) as context:
            read_audio_upload(file)

        self.assertEqual(context.exception.status_code, 415)

    def test_empty_audio_is_rejected(self):
        file = upload(b"", "meeting.wav", "audio/wav")

        with self.assertRaises(HTTPException) as context:
            read_audio_upload(file)

        self.assertEqual(context.exception.status_code, 422)

    @patch("app.api.routes.transcripts.MAX_AUDIO_BYTES", 4)
    def test_oversized_audio_is_rejected(self):
        file = upload(b"12345", "meeting.wav", "audio/wav")

        with self.assertRaises(HTTPException) as context:
            read_audio_upload(file)

        self.assertEqual(context.exception.status_code, 413)


if __name__ == "__main__":
    unittest.main()
