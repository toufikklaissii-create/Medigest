"""Montant en toutes lettres, en français (orthographe traditionnelle), pour les factures."""

from decimal import ROUND_HALF_UP, Decimal

UNITS = [
    "zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
    "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize",
    "dix-sept", "dix-huit", "dix-neuf",
]
TENS = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}


def _below_100(n):
    if n < 20:
        return UNITS[n]
    tens, unit = divmod(n, 10)
    if tens in (7, 9):
        # 70-79 = soixante + 10..19 ; 90-99 = quatre-vingt + 10..19
        base = "soixante" if tens == 7 else "quatre-vingt"
        rest = 10 + unit
        if tens == 7 and unit == 1:
            return "soixante et onze"
        return f"{base}-{UNITS[rest]}"
    if tens == 8:
        return "quatre-vingts" if unit == 0 else f"quatre-vingt-{UNITS[unit]}"
    if unit == 0:
        return TENS[tens]
    if unit == 1:
        return f"{TENS[tens]} et un"
    return f"{TENS[tens]}-{UNITS[unit]}"


def _below_1000(n, final=True):
    """`final` : le nombre termine l'expression (« deux cents ») ou est suivi de « mille » (« deux cent mille »)."""
    hundreds, rest = divmod(n, 100)
    if hundreds == 0:
        words = _below_100(rest)
        # « quatre-vingt mille » : vingt ne prend pas de s devant mille.
        return words[:-1] if not final and words.endswith("quatre-vingts") else words
    head = "cent" if hundreds == 1 else f"{UNITS[hundreds]} cent"
    if rest == 0:
        return f"{head}s" if hundreds > 1 and final else head
    tail = _below_100(rest)
    if not final and tail.endswith("quatre-vingts"):
        tail = tail[:-1]
    return f"{head} {tail}"


def nombre_en_lettres(n):
    """Entier positif en lettres : 1250 → « mille deux cent cinquante »."""
    n = int(n)
    if n < 0:
        raise ValueError("Montant négatif.")
    if n == 0:
        return "zéro"
    parts = []
    for value, singular, plural in ((10**9, "milliard", "milliards"), (10**6, "million", "millions")):
        count, n = divmod(n, value)
        if count:
            parts.append(f"{nombre_en_lettres(count)} {singular if count == 1 else plural}")
    thousands, n = divmod(n, 1000)
    if thousands:
        parts.append("mille" if thousands == 1 else f"{_below_1000(thousands, final=False)} mille")
    if n:
        parts.append(_below_1000(n))
    return " ".join(parts)


def montant_en_lettres(amount):
    """350 → « trois cent cinquante dirhams » ; 1250.50 → « … dirhams et cinquante centimes »."""
    amount = Decimal(amount or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    dirhams = int(amount)
    centimes = int((amount - dirhams) * 100)

    words = nombre_en_lettres(dirhams)
    if dirhams >= 10**6 and dirhams % 10**6 == 0:
        unit = "de dirhams"  # « un million de dirhams »
    else:
        unit = "dirhams" if dirhams >= 2 else "dirham"
    text = f"{words} {unit}"
    if centimes:
        text += f" et {nombre_en_lettres(centimes)} centime{'s' if centimes >= 2 else ''}"
    return text
