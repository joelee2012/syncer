import asyncio
import logging
from argparse import ArgumentParser
from pathlib import Path

import yaml
from anyio import wrap_file
from httpx import AsyncClient, AsyncHTTPTransport
from rich.logging import RichHandler
from rich.progress import Progress


def main():
    parser = ArgumentParser(prog='syncer',
                            description='What the program does',
                            epilog='Text at the bottom of help')
    # parser.add_argument('repo')
    parser.add_argument('-f', '--config', type=open,
                        help="configuration file name", required=True)
    parser.add_argument('-w', '--worker', type=int, default=3,
                        help="parallel workers")
    parser.add_argument('-r', '--retries', type=int, default=3,
                        help="retries to download")
    parser.add_argument('-c', '--chart', help="helm chart name")
    parser.add_argument('-t', '--timeout', default=10,
                        type=int, help="connection timeout")
    parser.add_argument('-d', '--debug', action='store_true',
                        help="enable debug mode")
    args = parser.parse_args()
    log_level = logging.DEBUG if args.debug else logging.ERROR
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=log_level,
        handlers=[RichHandler(show_time=False, show_level=False)])
    with Progress() as progress:
        asyncio.run(execute(args, progress), debug=args.debug)


# class IndexManager:

#     indexes = {}

#     @classmethod
#     async def get_index(cls, url):
#         indexes = cls.indexes
#         if url not in indexes:
#             async with AsyncClient(timeout=timeout) as client:
#                 indexes[url] = yaml.safe_load(await client.get(f'{url}/index.yaml'))
#         return indexes[url]


# async def get_index(repo, timeout=10):
#     if repo not in indexes:
#         async with AsyncClient(follow_redirects=True, timeout=timeout) as client:
#             resp = await client.get(f'{repo}/index.yaml')
#             indexes[repo] = yaml.safe_load(resp.text)
#     return indexes[repo]
indexes = {}


async def get_index(repo, timeout=10):
    if repo not in indexes:
        async with AsyncClient(timeout=timeout) as client:
            resp = await client.get(f'{repo}/index.yaml')
            indexes[repo] = yaml.safe_load(resp.text)
    return indexes[repo]


async def get_chart_url(repo, name, version='', timeout=10):
    index = await get_index(repo, timeout)
    if version and version != 'latest':
        for c in index['entries'][name]:
            if c['version'] == version:
                return c['urls'][0]
    return index['entries'][name][0]['urls'][0]


async def execute(args, progress):
    conf = yaml.safe_load(args.config)
    queue = asyncio.Queue()
    for chart in conf['charts']:
        chart['rtRepo'] = conf['rtRepo']
        chart['cache'] = conf['cache']
        queue.put_nowait(chart)
        await get_index(chart['repo'])
    tasks = []
    for i in range(args.worker):
        task = asyncio.create_task(
            worker(queue, progress, args.retries, args.timeout), name=f'worker-{i}')
        tasks.append(task)
    await queue.join()
    cmd = f'jf rt curl -XPOST /api/helm/{conf["rtRepo"]}/reindex'
    await run_shell(cmd, progress)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def download_chart(url, progress, task, cache_path, retries, timeout):
    transport = AsyncHTTPTransport(retries=retries)
    client = AsyncClient(follow_redirects=True,
                         timeout=timeout, transport=transport)
    async with client.stream("GET", url) as response:
        total = int(response.headers["Content-Length"])
        progress.reset(task, total=total)
        # task = progress.add_task(f"Download {filename}", total=total)
        async with wrap_file(cache_path.open('w+b')) as fd:
            async for chunk in response.aiter_bytes():
                progress.update(
                    task, completed=response.num_bytes_downloaded)
                await fd.write(chunk)


async def run_shell(cmd, progress):
    proc = await asyncio.create_subprocess_shell(cmd,
                                                 stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        progress.log(stderr)


async def worker(queue, progress, retries, timeout):
    while True:
        info = await queue.get()
        rt_repo = info.pop('rtRepo')
        cache_dir = info.pop('cache')
        url = await get_chart_url(**info)
        path = Path(url)
        filename = path.name
        version = path.stem.split('-')[-1]
        cache_path = Path(f'{cache_dir}/{filename}')
        task = progress.add_task(
            f"Download {filename}", start=False, total=None)
        try:
            if not cache_path.exists():
                await download_chart(url, progress, task, cache_path, retries, timeout)
            else:
                progress.reset(task, total=cache_path.stat().st_size)
                progress.update(task, completed=cache_path.stat().st_size)
            cmd = f'jf rt u {cache_path} {rt_repo}/{info["name"]}/{version}/'
            await run_shell(cmd, progress)
        except Exception as e:
            progress.reset(task, start=False,
                           description=f'[red]Download {filename} failed, {e}')
            raise
        finally:
            queue.task_done()

if __name__ == '__main__':
    main()
