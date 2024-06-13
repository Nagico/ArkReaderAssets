import os
import hashlib
import asyncio
from concurrent.futures import ProcessPoolExecutor


def compute_md5(file_path):
    """Compute the MD5 hash of a file."""
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return file_path, hash_md5.hexdigest()
    except Exception as e:
        return file_path, str(e)


def get_all_files(directory):
    """Get all file paths in the given directory."""
    file_paths = []
    for root, _, files in os.walk(directory):
        for file in files:
            file_paths.append(os.path.join(root, file))
    return file_paths


async def compute_md5_async(file_path, executor):
    """Asynchronously compute the MD5 hash of a file using the executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, compute_md5, file_path)


async def compute_md5_for_files(file_paths, executor):
    """Asynchronously compute MD5 for all files using the executor."""
    tasks = [compute_md5_async(file_path, executor) for file_path in file_paths]
    results = await asyncio.gather(*tasks)
    return dict(results)


async def download_file(url, save_path):
    """Simulate downloading a file (replace with actual download logic)."""
    await asyncio.sleep(1)  # Simulate network delay
    with open(save_path, 'wb') as f:
        f.write(os.urandom(1024))  # Simulate file content
    return save_path


async def download_and_compute_md5(url, save_path, executor):
    """Download a file and compute its MD5 hash."""
    file_path = await download_file(url, save_path)
    return await compute_md5_async(file_path, executor)


async def main():
    # Create a persistent process pool executor
    with ProcessPoolExecutor() as executor:
        # Example: Compute MD5 for all files in a directory
        directory = r"C:\Users\co\Documents\Work\repo\ArknightsAssets\files\raw\Android"  # Replace with your directory path
        file_paths = get_all_files(directory)
        md5_dict = await compute_md5_for_files(file_paths, executor)
        for file_path, md5 in md5_dict.items():
            print(f"{file_path}: {md5}")

        # Example: Asynchronously download files and compute their MD5
        # urls = ["http://example.com/file1", "http://example.com/file2"]  # Replace with actual URLs
        # save_paths = ["path/to/save/file1", "path/to/save/file2"]  # Replace with actual save paths
        # tasks = [download_and_compute_md5(url, save_path, executor) for url, save_path in zip(urls, save_paths)]
        # results = await asyncio.gather(*tasks)
        # for file_path, md5 in results:
        #     print(f"{file_path}: {md5}")

if __name__ == "__main__":
    asyncio.run(main())
