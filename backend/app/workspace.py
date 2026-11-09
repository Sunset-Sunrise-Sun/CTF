from pathlib import Path
from uuid import UUID


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def challenge_lexical(self, challenge_id: str) -> Path:
        """Return the unresolved challenge directory.

        Tool boundary checks need the lexical path so they can reject a
        challenge directory that is itself a junction/reparse point; resolving
        first would hide that fact.
        """
        if str(UUID(challenge_id)) != challenge_id:
            raise ValueError("Invalid challenge ID")
        return self.root / challenge_id

    def challenge(self, challenge_id: str) -> Path:
        candidate = self.challenge_lexical(challenge_id).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("Path outside workspace")
        return candidate

    def resolve(self, relative: str) -> Path:
        part = Path(relative)
        if part.is_absolute() or part.drive or ".." in part.parts or ":" in relative:
            raise ValueError("Path outside workspace")
        candidate = (self.root / part).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("Path outside workspace")
        return candidate
