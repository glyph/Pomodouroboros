from dataclasses import dataclass


@dataclass(frozen=True)
class Color:
    red: float
    green: float
    blue: float
    alpha: float
