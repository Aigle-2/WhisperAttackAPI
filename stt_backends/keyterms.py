PHONETIC_ALPHABET = [
    "Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf",
    "Hotel", "India", "Juliet", "Kilo", "Lima", "Mike", "November",
    "Oscar", "Papa", "Quebec", "Romeo", "Sierra", "Tango", "Uniform",
    "Victor", "Whiskey", "X-ray", "Yankee", "Zulu",
]

DEFAULT_DCS_KEYTERMS = [
    "Enfield", "Springfield", "Uzi", "Colt", "Dodge", "Ford", "Chevy", "Pontiac",
    "Overlord", "Magic", "Wizard", "Focus", "Darkstar", "Texaco", "Arco", "Shell",
    "Axeman", "JTAC", "request startup", "request taxi", "request takeoff",
    "request rejoin", "bogey dope", "ready to copy",
]

DEFAULT_STT_KEYTERM_SOURCES = [
    "phonetic_alphabet",
    "fuzzy_words",
    "word_mapping_replacements",
    "dcs_default",
    "custom",
]
