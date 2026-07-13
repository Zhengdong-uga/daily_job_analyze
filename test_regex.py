import re

word_to_num = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10
}

def text_to_int(text: str) -> int:
    text = text.lower().strip()
    if text in word_to_num:
        return word_to_num[text]
    try:
        return int(text)
    except ValueError:
        return 0

def extract_max_yoe(text: str) -> int:
    patterns = [
        r"(\d+)(?:\s*(?:-|to)\s*\d+)?\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp)",
        r"(?:minimum|at least|requires|requiring)\s+(?:of\s+)?(\d+)\+?\s*(?:years?|yrs?)",
        r"(one|two|three|four|five|six|seven|eight|nine|ten)(?:\s*(?:-|to)\s*(?:\w+))?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp)",
        r"(\d+)(?:\s*(?:-|to)\s*\d+)?\+?\s*(?:years?|yrs?)\s+(?:of\s+|in\s+|working\s+|with\s+|as\s+|building\s+|developing\s+)",
        r"(\d+)(?:\s*(?:-|to)\s*\d+)?\+?\s*(?:years?|yrs?)['’]\s*(?:experience|exp)"
    ]
    max_yoe = 0
    for p in patterns:
        for m in re.finditer(p, text, re.IGNORECASE):
            val = text_to_int(m.group(1))
            if 0 < val < 20: # ignore weirdly large numbers
                max_yoe = max(max_yoe, val)
    return max_yoe

tests = [
    "5 to 7 years of experience",
    "3 - 5 years of experience",
    "two to four years of experience",
    "5+ years' experience"
]
for t in tests:
    print(f"'{t}' -> {extract_max_yoe(t)}")
