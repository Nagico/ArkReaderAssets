import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import loguru

from utils.download import DownloadTool


class Extractor:
    ASSERT_STUDIO_URL = ("https://gh.con.sh/https://github.com/aelurum/AssetStudio/releases/download/v0.18.0"
                         "/AssetStudioModCLI_net8_portable.zip")

    def __init__(self, root: Path | None = None):
        if root is None:
            root = Path.cwd().parents[0]
        self.root = root
        self.tools_path = root / "scripts" / "tools"
        self.asset_studio_path = self.tools_path / "asset_studio"
        self.raw_path = root / "tmp" / "raw"
        self.dump_path = root / "tmp" / "dump"

        self.download_tool = DownloadTool(roads=8)

        self.logger = loguru.logger.bind(name="Extractor")

    async def start(self):
        await self._start()

    async def _start(self):
        await self.check_dotnet8()
        await self.prepare_tools()
        await self.extract()

    async def extract(self):
        if not self.raw_path.exists():
            self.logger.error("Raw files not found")
            return

        self.logger.info("Extracting raw files")

        command = [
            "dotnet",
            (self.asset_studio_path / "AssetStudioModCLI.dll").absolute().as_posix(),
            self.raw_path.absolute().as_posix(),
            "-o",
            self.dump_path.absolute().as_posix(),
            "--image-format",
            "webp",
            "-g",
            "containerFull",
            "--log-level",
            "debug",
        ]

        task = os.system(" ".join(command))

        if task != 0:
            msg = "Failed to extract"
            self.logger.error(msg)
            raise Exception(msg)

        self.logger.success("Extraction complete")
        shutil.rmtree(self.raw_path)

    async def check_dotnet8(self):
        result = await asyncio.create_subprocess_shell(
            "dotnet --list-runtimes",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = await result.communicate()
        if result.returncode != 0:
            msg = f"Failed to check dotnet runtime: {stderr.decode()}"
            self.logger.error(msg)
            raise Exception(msg)
        if b".NETCore.App 8" not in stdout:
            msg = "dotnet runtime 8 not found"
            self.logger.error(msg)
            raise Exception(msg)

        self.logger.info("dotnet runtime 8 found")

    async def prepare_tools(self):
        if not self.asset_studio_path.exists():
            self.logger.info("Asset Studio not found, fetching...")
            await self.download_asset_studio()
        else:
            self.logger.info("Asset Studio found")

    async def download_asset_studio(self):
        await self.download_tool.download(
            url=self.ASSERT_STUDIO_URL,
            path=self.tools_path / "asset_studio.zip",
            log=True,
            monitor_process=True
        )

        self.asset_studio_path.mkdir(parents=True, exist_ok=True)
        self.logger.info("Extracting Asset Studio")
        with zipfile.ZipFile(self.tools_path / "asset_studio.zip", 'r') as zip_ref:
            zip_ref.extractall(self.asset_studio_path)
            zip_ref.close()

        (self.tools_path / "asset_studio.zip").unlink()


async def main():
    extractor = Extractor()
    await extractor.start()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
