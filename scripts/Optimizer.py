import json
import os
import shutil
import subprocess
from pathlib import Path
import zstandard as zstd

import loguru
from PIL import Image
from tqdm.asyncio import tqdm_asyncio

from utils.executor import ParallelExecutor
from utils.filter import Filter


class Optimizer:
    def __init__(self, root: Path | None = None):
        if root is None:
            root = Path.cwd().parents[0]
        self.root = root
        self.tmp_path = self.root / "tmp"
        self.dump_path = self.tmp_path / "dump"
        self.opt_path = self.tmp_path / "opt"

        self.logger = loguru.logger.bind(name="Optimizer")

        with open("./config/optimizer.json", "r") as f:
            config = json.load(f)
        self.opt_rules = config["opt"]
        for rule in self.opt_rules:
            rule["match"] = Filter.compile(rule["file"])

        self.copy_rules = config["copy"]
        self.del_match = Filter.compile(config["del"])

        self.executor = ParallelExecutor(os.cpu_count() * 2)
        self.opt_tasks = []

    async def start(self):
        with self.executor:
            await self._start()

    async def _start(self):
        self.move_files()
        self.rename_dirs()
        self.remove_redundant()
        await self.check_ffmpeg()
        await self.optimize()

    def move_files(self):
        src = self.dump_path / "assets" / "torappu" / "dynamicassets"
        if not src.exists():
            return
        folders = [f for f in os.listdir(src) if os.path.isdir(src / f)]
        for folder in folders:
            shutil.move(src / folder, self.dump_path / folder)

        shutil.rmtree(self.dump_path / "assets")
    
    def rename_dirs(self):
        # del [uc] in dir name
        for dirpath, dirnames, filenames in os.walk(self.dump_path):
            for dirname in dirnames:
                if dirname.startswith("[uc]"):
                    new_name = dirname[4:]
                    os.rename(os.path.join(dirpath, dirname), os.path.join(dirpath, new_name))

    def remove_redundant(self):
        self.logger.info("Removing redundant files")
        count = 0
        for dirpath, dirnames, filenames in os.walk(self.dump_path):
            for filename in filenames:
                if self.del_match(filename):
                    os.remove(os.path.join(dirpath, filename))
                    self.logger.trace(f"Removed {filename}")
                    count += 1
                    continue

                if not filename.endswith('.webp'):
                    continue

                if '#' not in filename:
                    continue
                base_name = '#'.join(filename.split('#')[:-1])
                if base_name + '.webp' not in filenames and not (
                    base_name[-1] == '_' and base_name[:-1] + '.webp' in filenames
                ):
                    # self.logger.warning(f"Cannot find base name for {filename}")
                    continue

                file_to_delete = os.path.join(dirpath, filename)
                os.remove(file_to_delete)
                self.logger.trace(f"Removed {file_to_delete}")
                count += 1
        self.logger.info(f"Removed {count} redundant files")

    async def check_ffmpeg(self):
        command = "ffmpeg -version"
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if stderr:
            self.logger.error(f"Failed to check ffmpeg: {stderr}")
            return

    async def optimize(self):
        self.logger.info("Optimizing files")
        for file in self.dump_path.rglob("*"):
            if file.is_dir():
                continue
            for rule in self.opt_rules:
                path = file.relative_to(self.dump_path).as_posix()
                if rule["match"](path):
                    func = getattr(self, rule["action"])
                    options = rule.get("options", {})
                    full_path = file.absolute().as_posix()

                    if rule["action"] == "ffmpeg_audio":
                        self.opt_tasks.append(
                            self.executor.run(func, full_path, options["format"], options["bitrate"])
                        )
                    # elif rule["action"] == "pillow_webp":
                    #     self.opt_tasks.append(
                    #         self.executor.run(func, full_path, options["format"], options["quality"])
                    #     )
                    elif rule["action"] == "zstd":
                        if file.stat().st_size < options["min"]:
                            break
                        self.opt_tasks.append(
                            self.executor.run(func, full_path, options["level"])
                        )
                    break

        await tqdm_asyncio.gather(
            *self.opt_tasks,
            desc="Optimizing Files",
            unit="file",
        )

    @staticmethod
    def ffmpeg_audio(path: str, format: str, bitrate: int):
        command = f"ffmpeg -i {path} -b:a {bitrate}k {path[:-4]}.{format}"
        process = subprocess.run(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        if process.returncode != 0:
            print(f"Failed to optimize {path}: {process.stderr}")
            raise Exception(f"Failed to optimize {path}: {process.stderr}")

        os.remove(path)

    @staticmethod
    def pillow_webp(path: str, format: str, quality: int):
        img = Image.open(path)
        img.save(path[:-4] + format, "webp", quality=quality)

    @staticmethod
    def zstd(path: str, level: int):
        with open(path, "rb") as f:
            data = f.read()
        
        # check if file is already compressed
        if data[:4] == b'\x28\xb5\x2f\xfd':
            return

        cctx = zstd.ZstdCompressor(level=level)
        compressed = cctx.compress(data)

        with open(path, "wb") as f:
            f.write(compressed)


if __name__ == "__main__":
    async def main():
        optimizer = Optimizer()
        await optimizer.start()

    import asyncio
    asyncio.run(main())
