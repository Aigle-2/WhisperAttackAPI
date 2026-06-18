import re


def compact_spelled_codes(text: str, min_letters: int = 2, max_letters: int = 6) -> str:
    """
    Compact transcribed spelled-letter sequences into aviation code tokens.
    """
    text = re.sub(r"(?<=\b[A-Za-z])[-./](?=[A-Za-z]\b)", " ", text)
    tokens = text.split()
    compacted_tokens: list[str] = []
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if not re.fullmatch(r"[A-Za-z]", token):
            compacted_tokens.append(token)
            index += 1
            continue

        letters = []
        end_index = index
        while end_index < len(tokens) and re.fullmatch(r"[A-Za-z]", tokens[end_index]):
            letters.append(tokens[end_index].upper())
            end_index += 1

        if min_letters <= len(letters) <= max_letters:
            compacted_tokens.append("".join(letters))
            index = end_index
            continue

        compacted_tokens.extend(tokens[index:end_index])
        index = end_index

    return " ".join(compacted_tokens)
