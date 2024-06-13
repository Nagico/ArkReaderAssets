from pathlib import Path

import loguru

logger = loguru.logger.bind(name="GameVersion")


class GameVersion:
    FILENAME = "version.txt"

    client_version: str
    resource_version: str

    def __init__(
        self,
        client_version: str = "",
        resource_version: str = ""
    ) -> None:
        self.client_version = client_version
        self.resource_version = resource_version

    def __str__(self) -> str:
        return f"Client Version: {self.client_version}, Resource Version: {self.resource_version}"

    def __repr__(self) -> str:
        return f"GameVersion(client_version={self.client_version}, resource_version={self.resource_version})"

    def __eq__(self, other: "GameVersion") -> bool:
        return self.client_version == other.client_version and self.resource_version == other.resource_version

    def _load(self, path: Path | str) -> None:
        if isinstance(path, str):
            path = Path(path)

        path = path / self.FILENAME
        if not path.exists():
            logger.info(f"Version file not found: {path}")
            return

        with open(path, 'r') as f:
            data = f.read()
        self.client_version, self.resource_version = data.splitlines()
        logger.trace(f"Loaded version: {self} from {path}")
        return

    @staticmethod
    def load(path: Path | str) -> "GameVersion":
        version = GameVersion()
        version._load(path)
        return version

    def save(self, path: Path | str) -> None:
        if isinstance(path, str):
            path = Path(path)

        path = path / self.FILENAME
        with open(path, 'w') as f:
            f.write(f"{self.client_version}\n{self.resource_version}")
        logger.trace(f"Saved version: {self} to {path}")
