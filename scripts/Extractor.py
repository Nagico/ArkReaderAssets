import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import loguru
from Crypto.Cipher import AES

from utils.download import DownloadTool


class Extractor:
    ASSERT_STUDIO_URL = ("https://gh.con.sh/https://github.com/aelurum/AssetStudio/releases/download/v0.18.0"
                         "/AssetStudioModCLI_net8_portable.zip")
    
    FLACT_URL = ("https://gh.con.sh/https://github.com/google/flatbuffers/releases/download/v24.3.25"
                 "/Linux.flatc.binary.clang++-15.zip")
    
    FBS_PATH = ("https://gh.con.sh/https://github.com/MooncellWiki/OpenArknightsFBS/archive/refs/heads/main.zip")

    def __init__(self, root: Path | None = None):
        if root is None:
            root = Path.cwd().parents[0]
        self.root = root
        self.tools_path = root / "scripts" / "tools"
        self.asset_studio_path = self.tools_path / "asset_studio"
        self.flatc_path = self.tools_path / "flatc"
        self.fbs_path = self.tools_path / "fbs"
        self.raw_path = root / "tmp" / "raw"
        self.dump_path = root / "tmp" / "dump"

        self.download_tool = DownloadTool(roads=8)

        self.logger = loguru.logger.bind(name="Extractor")
        with open("./config/downloader.json") as f:
            config = json.load(f)
        self.filter = self.handle_filter(config["filter"])
    
    @staticmethod
    def handle_filter(filter: list[str]):
        results = []
        for f in filter:
            if '*' in f:
                f = f.split('*')[0]
            if '.ab' in f:
                f = f.split('.ab')[0]
            results.append(f"assets/torappu/dynamicassets/{f}")
        return results

    async def start(self):
        await self._start()

    async def _start(self):
        await self.check_dotnet8()
        await self.prepare_tools()
        # await self.extract()
        await self.covert_json()

    async def extract(self):
        if not self.raw_path.exists():
            self.logger.error("Raw files not found")
            return

        self.logger.info("Extracting raw files")

        command = [
            "bash -c",
            "\"" # no space after this
            "dotnet",
            (self.asset_studio_path / "AssetStudioModCLI.dll").absolute().as_posix(),
            (self.raw_path / "Android").absolute().as_posix(),
            "-o",
            self.dump_path.absolute().as_posix(),
            "--image-format",
            "webp",
            "-g",
            "containerFull",
            "--log-level",
            "info",
            "--filter-by-text", 
            ",".join(self.filter),
            "--max-export-tasks",
            "48"
            # no space before this
            "\"",
        ]

        self.logger.info(f"Running command: {' '.join(command)}")

        task = subprocess.run(' '.join(command), shell=True)

        if task.returncode != 0:
            msg = "Failed to extract"
            self.logger.error(msg)
            raise Exception(msg)

        self.logger.success("Extraction complete")
        # shutil.rmtree(self.raw_path)

    @staticmethod
    def decrypt_textasset(stream: bytes) -> bytes:
        def unpad(data: bytes) -> bytes:
            end_index = len(data) - data[-1]
            return data[:end_index]

        CHAT_MASK = bytes.fromhex('554954704169383270484157776e7a7148524d4377506f6e4a4c49423357436c').decode()

        aes_key = CHAT_MASK[:16].encode()
        aes_iv = bytearray(
            buffer_bit ^ mask_bit
            for (buffer_bit, mask_bit) in zip(stream[:16], CHAT_MASK[16:].encode())
        )

        decrypted = (
            AES.new(aes_key, AES.MODE_CBC, aes_iv)
            .decrypt(stream[16:])
        )

        return unpad(decrypted)

    def decode_file(self, file_path: Path, fbs_path: Path) -> Path:
        with open(file_path, "rb") as f:
            data = f.read()
        with open(file_path, "wb") as f:
            f.write(data[128:])
        
        command = [
            (self.flatc_path / "flatc").absolute().as_posix(),
            "-o",
            file_path.parent.absolute().as_posix(),
            fbs_path.absolute().as_posix(),
            "--",
            file_path.absolute().as_posix(),
            "--json",
            "--strict-json",
            "--natural-utf8",
            "--defaults-json",
            "--unknown-json",
            "--raw-binary",
            "--force-empty",
        ]

        self.logger.info(f"Running command: {' '.join(command)}")

        task = subprocess.run(' '.join(command), shell=True)

        if task.returncode != 0:
            msg = f"Failed to convert {file_path.name}"
            self.logger.error(msg)
            raise Exception(msg)
        
        self.logger.info(f"Converted {file_path.name} to json")
        
        return file_path.parent / f"{file_path.stem}.json"

    async def covert_json(self):
        self.logger.info("Converting json files")

        fbs_folder = self.fbs_path / "OpenArknightsFBS-main" / "FBS"
        fbs_names = [file.name[:-4] for file in list(fbs_folder.glob("*.fbs"))]

        self.logger.info(f"Find FBS files: {fbs_names}")

        for path in self.dump_path.glob("**/*.bytes"):
            filename = path.name[:-6]
            fbs = None
            for f in fbs_names:
                if filename.startswith(f):
                    fbs = f
                    break
            if fbs is None:
                continue

            target_json = path.parent / f"{fbs}.json"
            if target_json.exists():
                path.unlink()
                continue

            json_path = self.decode_file(path, fbs_folder / f"{fbs}.fbs")
            json_path.rename(target_json)
            path.unlink()

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
            await self.download(self.ASSERT_STUDIO_URL, "asset_studio", self.asset_studio_path)
        else:
            self.logger.info("Asset Studio found")
        
        if not self.flatc_path.exists():
            self.logger.info("Flatc not found, fetching...")
            await self.download(self.FLACT_URL, "flatc", self.flatc_path)
        else:
            self.logger.info("Flatc found")
        flatc = self.flatc_path / "flatc"
        flatc.chmod(0o755)
        
        if not self.fbs_path.exists():
            self.logger.info("FBS not found, fetching...")
            await self.download(self.FBS_PATH, "fbs", self.fbs_path)
        else:
            self.logger.info("FBS found")

    async def download(self, url: str, name: str, path: Path):
        await self.download_tool.download(
            url=url,
            path=self.tools_path / f"{name}.zip",
            log=True,
            monitor_process=True
        )

        path.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Extracting {name}")
        with zipfile.ZipFile(self.tools_path / f"{name}.zip", 'r') as zip_ref:
            zip_ref.extractall(path)
            zip_ref.close()

        (self.tools_path / f"{name}.zip").unlink()

async def main():
    extractor = Extractor()
    await extractor.start()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
