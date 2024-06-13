import asyncio
import os
from concurrent.futures import ProcessPoolExecutor

from tqdm.asyncio import tqdm_asyncio

from utils.debug import is_debug


class ParallelExecutor:
    def __init__(self, max_workers: int | None = None):
        self.max_workers = max_workers
        if self.max_workers is None:
            self.executor = os.cpu_count()
        self.debug = is_debug()

        if not self.debug:
            self.executor = ProcessPoolExecutor(max_workers=self.max_workers)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.debug:
            self.executor.shutdown(wait=True)

    async def run(self, func, *args):
        if self.debug:
            return func(*args)
        return await asyncio.get_event_loop().run_in_executor(self.executor, func, *args)

    async def run_many(self, name, func, args_list):
        tasks = [self.run(func, *args) for args in args_list]
        return await tqdm_asyncio.gather(*tasks, desc=name, unit="file")
