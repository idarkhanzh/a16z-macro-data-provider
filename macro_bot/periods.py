"""BLS observation periods (monthly, quarterly, semiannual) and their ordering."""

from __future__ import annotations

from dataclasses import dataclass

_PER_YEAR = {"M": 12, "Q": 4, "S": 2}
_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


@dataclass(frozen=True, order=True)
class Period:
    """One observation period of a series, e.g. Period(2026, 9, "M") = September 2026.

    Ordering compares (year, number), which is only meaningful within one frequency;
    each BLS series has a single frequency, so that is all the bot ever compares.
    """

    year: int
    number: int  # month 1-12, quarter 1-4 or half 1-2
    freq: str = "M"  # "M", "Q" or "S"

    @classmethod
    def parse(cls, year: str | int, code: str) -> Period | None:
        """Parse a BLS year + period code such as ("2026", "M09") or ("2026", "Q02").

        Returns None for annual averages (M13, Q05, S03) and annual data (A01).
        """
        freq, digits = code[:1], code[1:]
        if freq not in _PER_YEAR or not digits.isdigit():
            return None
        number = int(digits)
        if not 1 <= number <= _PER_YEAR[freq]:
            return None
        return cls(int(year), number, freq)

    @property
    def per_year(self) -> int:
        return _PER_YEAR[self.freq]

    @property
    def code(self) -> str:
        return f"{self.freq}{self.number:02d}"

    def shift(self, n: int) -> Period:
        """The period n steps later (negative n = earlier), crossing years as needed."""
        year, index = divmod(self.year * self.per_year + self.number - 1 + n, self.per_year)
        return Period(year, index + 1, self.freq)

    def label(self) -> str:
        """Human label used in message titles: "September 2026", "Q2 2026", "H1 2026"."""
        if self.freq == "M":
            return f"{_MONTHS[self.number - 1]} {self.year}"
        if self.freq == "Q":
            return f"Q{self.number} {self.year}"
        return f"H{self.number} {self.year}"

    def __str__(self) -> str:
        return f"{self.year} {self.code}"
