import mimetypes
import os
import uuid


def build_multipart_body(
    fields: list[tuple[str, str | None]],
    audio_path: str,
    file_field_name: str = "file",
) -> tuple[bytes, str]:
    """
    Build a multipart/form-data body without adding provider SDK dependencies.
    """
    boundary = f"----WhisperAttackAPI{uuid.uuid4().hex}"
    lines: list[bytes] = []

    for name, value in fields:
        if value is None or value == "":
            continue
        lines.extend([
            f"--{boundary}".encode("utf-8"),
            f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"),
            b"",
            str(value).encode("utf-8"),
        ])

    file_name = os.path.basename(audio_path)
    content_type = mimetypes.guess_type(audio_path)[0] or "audio/wav"
    with open(audio_path, "rb") as audio_file:
        audio_bytes = audio_file.read()

    lines.extend([
        f"--{boundary}".encode("utf-8"),
        f'Content-Disposition: form-data; name="{file_field_name}"; filename="{file_name}"'.encode("utf-8"),
        f"Content-Type: {content_type}".encode("utf-8"),
        b"",
        audio_bytes,
        f"--{boundary}--".encode("utf-8"),
        b"",
    ])

    return b"\r\n".join(lines), f"multipart/form-data; boundary={boundary}"
