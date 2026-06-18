"""Multipart helpers shared by the HTTP-based STT adapters.

Building the request body by hand avoids pulling in a provider SDK just to upload a
WAV file.
"""

from __future__ import annotations

import mimetypes
import os
import uuid


def build_multipart_body(
    fields: list[tuple[str, str | None]],
    audio_path: str,
    file_field_name: str = "file",
) -> tuple[bytes, str]:
    """Build a ``multipart/form-data`` body without a provider SDK dependency.

    Args:
        fields: Form fields as ``(name, value)`` pairs; blank/``None`` values skipped.
        audio_path: Path to the audio file to attach.
        file_field_name: The form field name for the file part.

    Returns:
        The encoded body bytes and the matching ``Content-Type`` header value.
    """
    boundary = f"----WhisperAttackAPI{uuid.uuid4().hex}"
    lines: list[bytes] = []

    for name, value in fields:
        if value is None or value == "":
            continue
        lines.extend(
            [
                f"--{boundary}".encode(),
                f'Content-Disposition: form-data; name="{name}"'.encode(),
                b"",
                str(value).encode("utf-8"),
            ]
        )

    file_name = os.path.basename(audio_path)
    content_type = mimetypes.guess_type(audio_path)[0] or "audio/wav"
    with open(audio_path, "rb") as audio_file:
        audio_bytes = audio_file.read()

    lines.extend(
        [
            f"--{boundary}".encode(),
            (
                f'Content-Disposition: form-data; name="{file_field_name}"; filename="{file_name}"'
            ).encode(),
            f"Content-Type: {content_type}".encode(),
            b"",
            audio_bytes,
            f"--{boundary}--".encode(),
            b"",
        ]
    )

    return b"\r\n".join(lines), f"multipart/form-data; boundary={boundary}"
