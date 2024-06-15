import os
import re
import io
import json
import shutil
import hashlib
import tarfile
import subprocess
from pathlib import Path
import zstandard as zstd
from concurrent.futures import ProcessPoolExecutor, as_completed

import loguru
from PIL import Image
from tqdm import tqdm

from utils.filter import Filter

ROOT = Path(__file__).parents[1]


class Optimizer:
    def __init__(self, root: Path | None = None):
        if root is None:
            root = ROOT
        self.root = root
        self.tmp_path = self.root / "tmp"
        self.dump_path = self.tmp_path / "dump"
        self.assets_path = self.root / "assets"

        self.logger = loguru.logger.bind(name="Optimizer")

        with open(ROOT / "scripts" / "config" / "optimizer.json", "r") as f:
            config = json.load(f)
        self.opt_rules = config["opt"]
        for rule in self.opt_rules:
            rule["match"] = Filter.compile(rule["file"])

        self.del_match = Filter.compile(config["del"])
        self.del_dirs = config["del_dir"]
        self.compress_dirs = config["compress_dir"]

        self.opt_tasks = []

    async def start(self):
        await self._start()

    async def _start(self):
        self.move_files()
        self.rename_dirs()
        self.del_dir()
        self.remove_redundant()
        self.move_upper(self.dump_path)
        self.rename_lower(self.dump_path / "gamedata")
        await self.check_ffmpeg()
        await self.optimize()
        self.compress_folders()
        self.merge()
        shutil.rmtree(self.dump_path)
    
    @staticmethod
    def compare_files(file1: str, file2: str, hash_algorithm=hashlib.md5) -> bool:
        hash_func = hash_algorithm()
        with open(file1, "rb") as f:
            hash_func.update(f.read())

        hash1 = hash_func.hexdigest()

        hash_func = hash_algorithm()
        with open(file2, "rb") as f:
            hash_func.update(f.read())

        hash2 = hash_func.hexdigest()

        return hash1 == hash2

    def merge(self):
        self.logger.info("Merging files")
        count = 0
        if not os.path.exists(self.assets_path):
            os.makedirs(self.assets_path)

        for root, dirs, files in os.walk(self.dump_path):
            relative_path = os.path.relpath(root, self.dump_path)
            dst_path = os.path.join(self.assets_path, relative_path)

            if not os.path.exists(dst_path):
                os.makedirs(dst_path)

            for file in files:
                src_file = os.path.join(root, file)
                dst_file = os.path.join(dst_path, file)

                if os.path.exists(dst_file) and self.compare_files(src_file, dst_file):
                    continue
                count += 1
                shutil.copy2(src_file, dst_file)
                self.logger.trace(f"Copied {src_file} to {dst_file}")
        
        self.logger.info(f"Copied {count} files")

    def del_dir(self):
        for dir in self.del_dirs:
            shutil.rmtree(self.dump_path / dir, ignore_errors=True)

    def rename_lower(self, path):
        for root, dirs, files in os.walk(path):
            for file in files:
                os.rename(os.path.join(root, file), os.path.join(root, file.lower()))

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
                file_path = os.path.join(dirpath, filename)
                if self.del_match(filename):
                    os.remove(file_path)
                    self.logger.trace(f"Removed {filename}")
                    count += 1
                    continue
                
                if "#" not in filename:
                    continue

                name, ext = os.path.splitext(filename)
                base_name = re.sub(r'(_#\d+|#\d+)$', '', name)
                base_file_path = os.path.join(dirpath, base_name + ext)
                if not os.path.exists(base_file_path):
                    continue
                
                file_size = os.path.getsize(file_path)
                base_file_size = os.path.getsize(base_file_path)

                if file_size <= base_file_size:
                    os.remove(file_path)
                else:
                    os.remove(base_file_path)
                    os.rename(file_path, base_file_path)

                self.logger.trace(f"Removed {filename}")
                count += 1

        self.logger.info(f"Removed {count} redundant files")

    def move_upper(self, base_path):
        self.logger.info("Moving files to the upper folder...")
        for root, dirs, files in os.walk(base_path, topdown=False):
            # 获取当前目录的父目录
            parent_dir = os.path.basename(root)

            if len(files) != 1:
                continue
            
            for file in files:
                file_name, file_ext = os.path.splitext(file)
                
                # 检查文件名是否与父目录名相同（除去扩展名）
                if file_name.lower() == parent_dir.lower():
                    # 构建源文件路径和目标文件路径
                    src_file_path = os.path.join(root, file)
                    dest_file_path = os.path.join(os.path.dirname(root), file)
                    
                    # 移动文件到上一级目录
                    shutil.move(src_file_path, dest_file_path)
                    self.logger.trace(f"Moved: {src_file_path} to {dest_file_path}")
            
            # 如果当前目录为空，则删除它
            if not os.listdir(root):
                os.rmdir(root)

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

    def compress_folders(self):
        tasks = []
        with ProcessPoolExecutor(max_workers=os.cpu_count()) as executor:
            for folder in self.compress_dirs:
                for subfolder in os.listdir(self.dump_path / folder):
                    tasks.append(
                        executor.submit(self.compress_folder, (self.dump_path / folder / subfolder).as_posix())
                    )
            
            with tqdm(total=len(tasks), desc="Compressing", unit="folder") as pbar:
                for _ in as_completed(tasks):
                    pbar.update(1)

    async def optimize(self):
        with ProcessPoolExecutor(max_workers=os.cpu_count()) as executor:
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
                                executor.submit(func, full_path, options["format"], options["bitrate"])
                            )
                        elif rule["action"] == "pillow_webp":
                            self.opt_tasks.append(
                                executor.submit(func, full_path, options["format"], options["quality"])
                            )
                        elif rule["action"] == "zstd":
                            if file.stat().st_size < options["min"]:
                                break
                            self.opt_tasks.append(
                                executor.submit(func, full_path, options["level"])
                            )
                        break
            
            with tqdm(total=len(self.opt_tasks), desc="Optimizing", unit="file") as pbar:
                for task in as_completed(self.opt_tasks):
                    pbar.update(1)

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

    @staticmethod
    def compress_folder(folder_path: str):
        # 获取文件夹的父目录和文件夹名称
        parent_dir, folder_name = os.path.split(folder_path.rstrip('/'))
        
        # 定义压缩文件的路径
        compressed_file_path = os.path.join(parent_dir, f"{folder_name}")
        
        # 创建 zstd 压缩器
        cctx = zstd.ZstdCompressor()

        tar_buffer = io.BytesIO()
    
        with tarfile.open(fileobj=tar_buffer, mode='w') as tar:
            # 遍历文件夹并添加到 tar 文件中
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    tar.add(file_path, arcname=os.path.relpath(file_path, folder_path))
        
        # 将 tar 文件指针重置到开始位置
        tar_buffer.seek(0)

        # 删除原文件夹
        shutil.rmtree(folder_path)
        
        # 压缩 tar 文件并写入到压缩文件中
        with open(compressed_file_path, 'wb') as compressed_file:
            with cctx.stream_writer(compressed_file) as compressor:
                shutil.copyfileobj(tar_buffer, compressor)

if __name__ == "__main__":
    async def main():
        optimizer = Optimizer()
        await optimizer.start()

    import asyncio
    asyncio.run(main())
