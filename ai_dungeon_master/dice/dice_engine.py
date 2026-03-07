import random

class DiceEngine:
    def __init__(self, seed: int = None):
        self.rng = random.Random(seed)

    def roll(self, sides: int, count: int = 1, modifier: int = 0) -> int:
        """Roll `count` N-sided dice and return the total plus modifier."""
        if sides < 2:
            raise ValueError(f"A die must have at least 2 sides, got {sides}.")
        if count < 1:
            raise ValueError(f"Must roll at least 1 die, got {count}.")
        return sum(self.rng.randint(1, sides) for _ in range(count)) + modifier

    def roll_notation(self, notation: str) -> int:
        """Parse and roll standard dice notation such as '2d6+3' or 'd20-1'."""
        import re
        notation = notation.strip().lower()
        match = re.fullmatch(r"^(\d*)d(\d+)([+-]\d+)?$", notation)
        if not match:
            raise ValueError(
                f"Invalid dice notation '{notation}'. "
                "Expected format: [N]dS[+/-M] (e.g. '2d6', 'd20', '3d8+2')."
            )
        count_str, sides_str, mod_str = match.groups()
        return self.roll(
            sides=int(sides_str),
            count=int(count_str) if count_str else 1,
            modifier=int(mod_str) if mod_str else 0,
        )

    def roll_advantage(self, sides: int = 20, modifier: int = 0) -> int:
        """Roll two dice and return the higher result plus modifier."""
        return max(self.rng.randint(1, sides), self.rng.randint(1, sides)) + modifier

    def roll_disadvantage(self, sides: int = 20, modifier: int = 0) -> int:
        """Roll two dice and return the lower result plus modifier."""
        return min(self.rng.randint(1, sides), self.rng.randint(1, sides)) + modifier

    def roll_drop_lowest(self, sides: int, count: int, drop: int = 1, modifier: int = 0) -> int:
        """Roll `count` dice, drop the `drop` lowest, return the total plus modifier."""
        if drop >= count:
            raise ValueError(f"Cannot drop {drop} dice when only rolling {count}.")
        rolls = [self.rng.randint(1, sides) for _ in range(count)]
        return sum(sorted(rolls)[drop:]) + modifier

    @staticmethod
    def parse_notation(notation: str) -> tuple[int, int, int]:
        """Parse dice notation into (sides, count, modifier).

        Examples: '2d6+3' → (6, 2, 3) | '1d8' → (8, 1, 0) | bad input → (6, 1, 0)
        """
        import re
        m = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", notation.strip().lower())
        if not m:
            return (6, 1, 0)
        count = int(m.group(1)) if m.group(1) else 1
        sides = int(m.group(2))
        modifier = int(m.group(3)) if m.group(3) else 0
        return (sides, count, modifier)

    def roll_exploding(self, sides: int, count: int = 1, modifier: int = 0, max_explosions: int = 10) -> int:
        """Roll dice that re-roll and accumulate on a max face result, return total plus modifier."""
        total = 0
        for _ in range(count):
            result = self.rng.randint(1, sides)
            total += result
            explosions = 0
            while result == sides and explosions < max_explosions:
                result = self.rng.randint(1, sides)
                total += result
                explosions += 1
        return total + modifier