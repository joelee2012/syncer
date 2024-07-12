import asyncio
import logging
import os
from argparse import ArgumentParser
from collections import namedtuple
from urllib.parse import urljoin

import yaml
from httpx import AsyncClient, BasicAuth
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

console = Console()
err_console = Console(stderr=True)


def main():
    parser = ArgumentParser(prog='syncer',
                            description='Sync helm chart')
    parser.add_argument('-f', '--config', type=open,
                        help="configuration file name", required=True)
    parser.add_argument('-w', '--worker', type=int, default=3,
                        help="parallel workers")
    parser.add_argument('--dest', required=True, help="dest url")
    parser.add_argument('--dest-auth', help="dest auth",
                        type=lambda s: BasicAuth(*s.split(':')))
    parser.add_argument('-d', '--debug', action='store_true',
                        help="enable debug mode")
    args = parser.parse_args()
    with Progress(
        SpinnerColumn(),
        *Progress.get_default_columns(),
        TimeElapsedColumn(),
    ) as progress:
        result = asyncio.run(execute(progress, args), debug=args.debug)
        for es in result:
            for e in es:
                err_console.log(e)


class IndexFile:
    def __init__(self, url) -> None:
        self.url = url
        self.index = {}

    async def load(self, client):
        resp = await client.get(self.url)
        resp.raise_for_status()
        self.index = yaml.safe_load(resp.text)

    def get_chart_url(self, name, version):
        if not self.index['entries'].get(name):
            return None
        for c in self.index['entries'][name]:
            if c['version'] == version:
                url = c['urls'][0]
                if not url.startswith('http'):
                    return urljoin(self.url, url)
                return url
        return None


async def wrap_response(progress, task, resp):
    async for chunk in resp.aiter_bytes():
        progress.update(task, advance=len(chunk))
        yield chunk


async def sync_chart(progress, client, chart, dest_auth=None):
    async with client.stream("GET", chart.url) as src_resp:
        src_resp.raise_for_status()
        size = int(src_resp.headers["Content-Length"])
        desc = f'[green]syncing {chart.name}:{chart.version}'
        task = progress.add_task(desc, total=size)
        resp = await client.put(chart.dest_url, auth=dest_auth, content=wrap_response(progress, task, src_resp))
        resp.raise_for_status()

Chart = namedtuple('Chart', ['name', 'version', 'url', 'dest_url'])


async def collect_charts(args, client):
    config = yaml.safe_load(args.config)
    queue = asyncio.Queue()
    for repo_url, repo_conf in config.items():
        index = IndexFile(f'https://{repo_url}/index.yaml')
        try:
            await index.load(client)
        except Exception as e:
            err_console.log(e)
            continue
        for name, versions in repo_conf['charts'].items():
            for version in versions:
                url = index.get_chart_url(name, version)
                if url:
                    filename = os.path.basename(url)
                    dest_url = f'{args.dest}/{name}/{version}/{filename}'
                    queue.put_nowait(Chart(name, version, url, dest_url))
                else:
                    err_console.log(f'Not found {name} '
                                    f'{version} in {repo_url}')
    return queue


async def execute(progress, args):
    async with AsyncClient(follow_redirects=True) as client:
        queue = await collect_charts(args, client)
        if queue.empty():
            return
        tasks = []
        for i in range(args.worker):
            task = asyncio.create_task(
                worker(progress, client, queue, args.dest_auth), name=f'worker-{i}')
            tasks.append(task)
        await queue.join()
        for task in tasks:
            task.cancel()
        return await asyncio.gather(*tasks, return_exceptions=True)


async def worker(progress, client, queue, dest_auth):
    exceptions = []
    while not queue.empty():
        chart = await queue.get()
        try:
            await sync_chart(progress, client, chart, dest_auth)
        except Exception as e:
            exceptions.append(e)
        finally:
            queue.task_done()
    return exceptions
