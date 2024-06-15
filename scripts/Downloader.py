import asyncio
import hashlib
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urljoin

import aiofile
import aiohttp
from loguru import logger
from tqdm import tqdm
from tqdm.asyncio import tqdm as async_tqdm
from bs4 import BeautifulSoup

from utils.checker import FileChecker
from utils.download import DownloadTool
from utils.filter import Filter
from utils.infos import HotUpdateInfo
from utils.versions import GameVersion
from utils.zip import ZipExtractor


ROOT = Path(__file__).parents[1]


class Downloader:
    CLIENT_HEADERS = {
        'X-Unity-Version': '2017.4.39f1',
        'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 12; 2201123C Build/V417IR)',
    }
    ANDROID_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 12; Pixel 3) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/91.0.4472.77 Mobile Safari/537.36',
    }
    NETWORK_CONFIG_URL = "https://ak-conf.hypergryph.com/config/prod/official/network_config"

    PLATFORM = "Android"

    apk_url: str
    version_url: str
    assets_url: str

    local_version: GameVersion
    remote_version: GameVersion

    def __init__(self, root: Path | None = None) -> None:
        self.session = aiohttp.ClientSession(
            headers=self.CLIENT_HEADERS,
        )
        self.logger = logger.bind(name="Downloader")

        if root is None:
            root = ROOT
        self.root = root
        self.raw_path = root / "tmp" / "raw"
        self.raw_path.mkdir(exist_ok=True, parents=True)
        self.hot_update_path = self.raw_path / "hot_update"
        self.hot_update_path.mkdir(exist_ok=True)

        self.local_version = GameVersion.load(self.root)
        self.logger.info(f"Local version: {self.local_version}")

        if self.local_version.client_version is None and self.local_version.resource_version is None:
            self.logger.info("Init mode")
            self.init_mode = True
        else:
            self.logger.info("Update mode")
            self.init_mode = False

        self.download_tool = DownloadTool()

        self.zip_extractor = ZipExtractor(self.raw_path)
        self.file_checker = FileChecker(self.raw_path / "Android")

        with open(ROOT / "scripts" / "config" / "downloader.json", "r") as f:
            data = json.load(f)
        self.hot_update_exclude_filter = Filter.compile(data["hot_update_list"]["exclude"])
        self.filter_str = data["filter"]
        self.filter = Filter.compile(data["filter"])

    async def start(self):
        with self.file_checker:
            async with self.session:
                await self._start()

    async def _start(self):
        await self.init_network()
        await self.get_version()

        self.assets_url = f"{self.assets_url}/{self.PLATFORM}/assets/{self.remote_version.resource_version}/"

        if self.local_version == self.remote_version:
            self.logger.info("Local version is up to date")
            return

        if self.local_version.client_version != self.remote_version.client_version:
            self.logger.info("Client version is different, need to download APK")
            await self.download_apk()
        else:
            self.logger.info("Client version is the same")

        # download assets
        await self.hot_update()
        shutil.rmtree(self.hot_update_path, ignore_errors=True)

        # update version
        self.remote_version.save(self.root)

    async def close(self):
        await self.session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def init_network(self):
        async with self.session.get(self.NETWORK_CONFIG_URL) as resp:
            data = await resp.read()
            network_config = json.loads(data)
        self.logger.trace(f"Get network config: {network_config}")
        # We ignore verifying the network config signature
        network_config = network_config["content"]
        # 去除转义
        network_config = network_config.replace('\\"', '"')
        network_config = json.loads(network_config)
        network_config = network_config['configs'][network_config['funcVer']]['network']
        self.logger.info(f"Network config: {network_config}")

        self.apk_url = network_config['pkgAd']
        self.version_url = network_config['hv'].replace("{0}", self.PLATFORM)
        self.assets_url = network_config['hu']

    async def get_version(self):
        async with self.session.get(self.version_url) as resp:
            data = await resp.read()
            version = json.loads(data)
            self.logger.trace(f"Get version: {version}")
        self.remote_version = GameVersion(
            client_version=version['clientVersion'],
            resource_version=version['resVersion']
        )
        self.logger.info(f"Remote version: {self.remote_version}")

    async def get_real_url(self, url: str, headers: dict[str, str] | None = None) -> str:
        if headers is None:
            headers = self.CLIENT_HEADERS

        async with self.session.get(url, allow_redirects=True, headers=headers) as resp:
            return str(resp.url)

    async def fetch_file(self, url: str, path: Path, skip: bool = False, log: bool = False, monitor_process: bool = False):
        if not url.endswith(".dat"):
            url = await self.get_real_url(url)
        await self.download_tool.download(url, path, skip=skip, log=log, monitor_process=monitor_process)

    async def download_apk(self):
        # fetch url
        async with self.session.get(self.apk_url) as resp:
            data = await resp.read()
            self.logger.trace(f"Gotten data from {self.apk_url}")
        android_url = self.find_apk_url(data)

        if not android_url:
            self.logger.error("No android download URL found")
            return
        path = self.raw_path / "arknights.apk"
        await self.fetch_file(android_url, path, skip=True, log=True, monitor_process=True)
        # unzip the file
        await self.zip_extractor.extract_file(path, filter_glob=[
            "assets/AB/Android/" + filter for filter in self.filter_str
        ])
        # recal md5
        await self.file_checker.cal_all()
        path.unlink()

    @staticmethod
    def find_apk_url(data: bytes) -> str | None:
        soup = BeautifulSoup(data, "html.parser")
        scripts = soup.find_all('script')
        # 查找包含安卓下载URL的<script>标签内容
        android_url = None
        pattern = re.compile(r'location\.href\s*=\s*"([^"]+)"')
        for script in scripts:
            if script.string:
                matches = pattern.findall(script.string)
                for match in matches:
                    if 'android' in match:
                        android_url = match
                        logger.debug(f"Found android APK download URL: {android_url}")
                        break
            if android_url:
                break
        return android_url

    def get_hot_update_file_url(self, info_name: str) -> str:
        return urljoin(
            self.assets_url,
            (info_name.rsplit('.', 1)[0] + ".dat")
            .replace('/', '_')
            .replace('#', '__')
        )

    async def download_asset(self, info: HotUpdateInfo) -> tuple[HotUpdateInfo, Path]:
        url = self.get_hot_update_file_url(info.name)
        zip_path = self.hot_update_path / url.split('/')[-1]

        await self.fetch_file(url, zip_path, monitor_process=False, skip=True)
        return info, zip_path

    def check_hot_update(self, infos: list[HotUpdateInfo]) -> tuple[list[HotUpdateInfo], list[HotUpdateInfo]]:
        download = []
        unpack = []
        for info in infos:
            if self.hot_update_exclude_filter(info.name):
                logger.trace(f"Skip {info.name}, excluded")
                continue

            if not self.filter(info.name):
                logger.trace(f"Skip {info.name}, not in filter")
                continue

            info.need_update = not self.file_checker.check_info(info)
            if info.need_update:
                unpack.append(info)

                url = self.get_hot_update_file_url(info.name)
                zip_path = self.hot_update_path / url.split('/')[-1]

                if zip_path.exists():
                    if info.total_size == zip_path.stat().st_size:
                        continue
                    else:
                        zip_path.unlink()
                download.append(info)
        return download, unpack

    async def hot_update(self):
        ab, pack = await self.get_file_list()

        download_list = ab
        if self.init_mode:
            download_list += pack

        download_info, unzip_info = self.check_hot_update(download_list)

        self.logger.info(f"Need to download {len(download_info)} files")
        self.logger.debug(f"Download list: {download_info}")

        # download tasks
        pos = self.download_tool.progress_bar_dispatcher.request()
        await async_tqdm.gather(
            *[self.download_asset(info) for info in download_info],
            desc="Downloading files",
            unit="file",
            position=pos,
        )
        self.download_tool.progress_bar_dispatcher.release(pos)

        infos = []
        zip_paths = []
        for info in unzip_info:
            url = self.get_hot_update_file_url(info.name)
            path = self.hot_update_path / url.split('/')[-1]
            infos.append(info)
            zip_paths.append(path)

        # extract files
        unzip_files = await self.zip_extractor.extract_files(zip_paths, filter_glob=self.filter_str)

        # check md5
        for info, files in zip(infos, unzip_files):
            if len(files) == 0:
                continue
            files = [Path(file) for file in files]
            if info.md5:
                md5 = await self.get_md5(files[0])
                if md5 != info.md5:
                    self.logger.warning(f"MD5 not match: {md5} != {info.md5}")
                await self.file_checker.update(files[0], md5)
            else:
                await self.file_checker.cal_files(files)
        await self.file_checker.save()

    async def get_file_list(self) -> tuple[list[HotUpdateInfo], list[HotUpdateInfo]]:
        url = urljoin(self.assets_url, "./hot_update_list.json")
        async with self.session.get(url) as resp:
            data = await resp.read()
            self.logger.trace(f"Get file list: {data}")
        file_list = json.loads(data)
        assert file_list['versionId'] == self.remote_version.resource_version

        ab_infos = [
            HotUpdateInfo.from_dict(info)
            for info in file_list['abInfos']
        ]

        pack_infos = [
            HotUpdateInfo.from_dict(info)
            for info in file_list['packInfos']
        ]

        self.logger.info(f"Hot update file list: {len(ab_infos)}, {len(pack_infos)} files")
        return ab_infos, pack_infos

    @staticmethod
    async def get_md5(path: Path) -> str:
        md5 = hashlib.md5()
        async with aiofile.async_open(path, 'rb') as f:
            async for chunk in f.iter_chunked():
                if isinstance(chunk, bytes):
                    md5.update(chunk)
                else:
                    md5.update(await chunk)

        md5 = md5.hexdigest()
        logger.bind(name="MD5").trace(f"Get MD5 of {path}: {md5}")
        return md5


async def main():
    async with Downloader() as downloader:
        await downloader.start()


if __name__ == "__main__":
    logger.remove()
    logger.add(lambda msg: tqdm.write(msg, end=""), colorize=True)

    asyncio.run(main())
