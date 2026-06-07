def ascii_safe(text: str) -> str:
    return text.encode('ascii', 'ignore').decode('ascii')
