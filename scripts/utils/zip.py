import asyncio
import zipfile
import os
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import cpu_count
from pathlib import Path
from typing import Any

from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio

from utils.debug import is_debug
from utils.filter import Filter


def _extract(
        asset_path: str,
        zip_path: str,
        filter_glob: list[str] | str | None = None
) -> list[str]:
    if isinstance(filter_glob, str):
        filter_glob = [filter_glob]
    if filter_glob is None:
        filter_glob = []

    match = Filter.compile(filter_glob)

    try:
        unzip_files = []

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            members = [m for m in zip_ref.namelist() if match(m)]
            total_files = len(members)

            def unzip():
                for member in members:
                    # 构造目标文件路径
                    if member.startswith('assets/AB'):
                        target_path = os.path.join(asset_path, os.path.relpath(member, 'assets/AB'))
                    else:
                        target_path = os.path.join(asset_path, "Android", member)
                    target_dir = os.path.dirname(target_path)

                    # 创建目标文件夹
                    if not os.path.exists(target_dir):
                        os.makedirs(target_dir, exist_ok=True)

                    # 解压文件
                    with zip_ref.open(member) as source, open(target_path, 'wb') as target:
                        target.write(source.read())

                    unzip_files.append(target_path)

            if total_files > 100:
                with tqdm(total=total_files, desc=f"Extracting {zip_path}", unit="file") as pbar:
                    unzip()
                    pbar.update(1)
            else:
                unzip()

        return unzip_files
    except Exception as e:
        print(f"Failed to extract {zip_path}: {e}")
        # return []
        raise e


class ZipExtractor:
    def __init__(self, extract_path: Path):
        self.asset_path = str(extract_path)
        self.process_num = cpu_count()
        self.debug = is_debug()
        if not self.debug:
            self.executor = ProcessPoolExecutor(max_workers=self.process_num)

    def __enter__(self) -> "ZipExtractor":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if not self.debug:
            self.executor.shutdown(wait=True)

    async def extract_files(
        self,
        zip_paths: list[Path],
        filter_glob: list[str] | None = None,
    ):
        tasks = [self.extract_file(str(zip_path), filter_glob) for i, zip_path in enumerate(zip_paths)]
        return await tqdm_asyncio.gather(
            *tasks,
            desc="Extracting Zip Files",
            unit="file",
        )

    async def extract_file(
        self,
        zip_path: Path | str,
        filter_glob: list[str] | str | None = None
    ) -> list[str]:
        if isinstance(zip_path, Path):
            zip_path = str(zip_path)
        if not self.debug:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(self.executor, _extract, self.asset_path, zip_path, filter_glob)
        else:
            return _extract(self.asset_path, zip_path, filter_glob)


async def main():
    with ZipExtractor(Path("extract")) as extractor:
        await extractor.extract_files([
            Path(r"C:\Users\co\Documents\Work\repo\ArknightsAssets\files\raw\tmp\arts_items_item_icons_stack_hub.dat"),
            Path(r"C:\Users\co\Documents\Work\repo\ArknightsAssets\files\raw\tmp\arts_items_optionalvoucheritembgdecs_pic_hub.dat"),
        ])


if __name__ == "__main__":
    asyncio.run(main())
