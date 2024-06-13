import asyncio
from pathlib import Path

import loguru
from DownloadKit import DownloadKit
from DownloadKit.mission import Mission
from tqdm import tqdm

from utils.dispatcher import PositionDispatcher


class DownloadTool:
    def __init__(
        self,
        retry: int = 3,
        roads: int = 32,
        interval: float = 0.5,
        split: bool = True,
        block_size: str = "16m",
    ):
        self.download_kit = DownloadKit()
        self.download_kit.set.log.log_nothing()
        self.download_kit.set.log.print_nothing()
        self.download_kit.set.retry(retry)
        self.download_kit.set.roads(roads)
        self.download_kit.set.interval(interval)
        self.download_kit.set.split(split)
        self.download_kit.set.block_size(block_size)

        self.logger = loguru.logger.bind(name="DownloadTool")

        self.progress_bar_dispatcher = PositionDispatcher()

    async def monitor_progress(self, mission: Mission, log: bool):
        """
        监控下载任务进度并使用tqdm显示进度条
        """
        while mission.file_name is None:
            await asyncio.sleep(1)
        total_size = mission.size
        pos = self.progress_bar_dispatcher.request()
        if log:
            self.logger.info(f"Downloading {mission.file_name}")
        with tqdm(
                total=total_size,
                desc=f"Downloading {mission.file_name}",
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
                position=pos,
                leave=False
        ) as pbar:
            while not mission.is_done:
                pbar.n = mission.rate / 100 * total_size
                pbar.refresh()
                await asyncio.sleep(1)
        self.progress_bar_dispatcher.release(pos)
        if log:
            self.logger.info(f"Downloaded {mission.file_name}")

    async def download(
        self,
        url: str,
        path: Path,
        skip: bool = False,
        log: bool = False,
        monitor_process: bool = False
    ) -> None:
        self.logger.trace(f"Adding {url} to download queue")
        mission = self.download_kit.add(
            file_url=url,
            goal_path=path.parents[0],
            rename=path.stem,
            suffix=path.suffix[1:],
            file_exists="overwrite" if not skip else "skip",
            allow_redirects=True,
        )

        loop = asyncio.get_event_loop()

        async def download():
            await loop.run_in_executor(None, lambda: mission.wait(show=False))

        if monitor_process:
            await asyncio.gather(
                download(),
                self.monitor_progress(mission, log),
            )
        else:
            await asyncio.gather(
                download(),
            )
