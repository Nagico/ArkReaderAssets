import asyncio
import hashlib
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import cpu_count
from pathlib import Path

import tqdm.asyncio

from .debug import is_debug
from .infos import HotUpdateInfo


class FileChecker:
    FILENAME = "md5.data"

    def __init__(self, path: Path) -> None:
        self._data = {}
        self.path = path
        self.data_path = path.parents[1] / "assets" / self.FILENAME
        self.debug = is_debug()
        self.load()

        self.worker_num = cpu_count()
        if not self.debug:
            self.executor = ProcessPoolExecutor(max_workers=self.worker_num)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.debug:
            self.executor.shutdown(wait=True)

    def load(self) -> None:
        if not self.data_path.exists():
            return
        with open(self.data_path, 'r') as f:
            data = f.read().splitlines()

        for i in range(0, len(data), 2):
            self._data[data[i]] = data[i + 1]

    async def save(self) -> None:
        data = []
        for key, value in self._data.items():
            data.append(key)
            data.append(value)
        with open(self.data_path, 'w') as f:
            f.write('\n'.join(data))

    @staticmethod
    def compute_md5(file_path: str) -> str | None:
        """Compute the MD5 hash of a file."""
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception:
            return None

    async def compute_md5_async(self, file_path: Path):
        """Asynchronously compute the MD5 hash of a file using the executor."""
        if not self.debug:
            loop = asyncio.get_event_loop()
            md5 = await loop.run_in_executor(self.executor, self.compute_md5, str(file_path.absolute()))
            return {file_path.relative_to(self.path).as_posix(): md5}
        else:
            return {file_path.relative_to(self.path).as_posix(): self.compute_md5(str(file_path.absolute()))}

    async def compute_md5_for_files(self, file_paths: list[Path]) -> dict[Path, str]:
        """Asynchronously compute MD5 for all files using the executor."""
        tasks = [self.compute_md5_async(file_path) for file_path in file_paths]
        results = await tqdm.asyncio.tqdm_asyncio.gather(
            *tasks, desc="Computing MD5", unit="file"
        )
        md5s = {}
        for result in results:
            md5s.update(result)
        return md5s

    async def clear(self) -> None:
        self._data.clear()
        await self.save()

    async def update(self, file: Path | str, md5: str) -> None:
        if isinstance(file, str):
            file = Path(file)
        assert file.exists()
        assert file.is_file()
        # assert file in self.path

        self._data[file.relative_to(self.path).as_posix()] = md5
        # await self.save()

    async def cal_all(self) -> None:
        await self.clear()

        files = [file for file in self.path.rglob("*") if file.is_file()]
        await self.cal_files(files)
        await self.save()

    async def cal_files(self, files: list[Path]) -> None:
        self._data.update(await self.compute_md5_for_files(files))
        # await self.save()

    async def cal_file(self, file: Path):
        assert file.exists()
        assert file.is_file()
        # assert file in self.path

        self._data[file.relative_to(self.path).as_posix()] = await self.compute_md5_async(file)
        # await self.save()

    def check(self, file: Path, md5: str) -> bool:
        if file.relative_to(self.path).as_posix() not in self._data:
            return False

        return self._data[file.relative_to(self.path)] == md5

    def check_info(self, info: HotUpdateInfo) -> bool:
        return info.name in self._data and self._data[info.name] == info.md5
        # file = self.path / "Android" / info.name
        # return self.check(file, info.md5)


async def main():
    with FileChecker(Path("../files/raw/Android")) as fc:
        await fc.cal_all()


if __name__ == "__main__":
    asyncio.run(main())
