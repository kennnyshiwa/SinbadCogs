import asyncio
import discord
from redbot.core import commands, checks
from redbot.core.config import Config
from redbot.core.i18n import Translator, cog_i18n

from .message import SchedulerMessage
from .logs import get_logger

from .tasks import Task

_ = Translator("And I think it's gonna be a long long time...", __file__)


@cog_i18n(_)
class Scheduler(commands.Cog):
    """
    A somewhat sane scheduler cog
    """

    __version__ = "1.0.0"
    __author__ = "mikeshardmind(Sinbad)"
    __flavor_text__ = "This is mediocre first effort, to be improved."
    # pending actually allowing it to be loaded by adding a setup once ready

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=78631113035100160, force_registration=True
        )
        self.config.register_channel(tasks={})  # Serialized Tasks go in here.
        self.log = get_logger("sinbadcogs.scheduler")
        self.bg_loop_task = bot.loop.create_task(self.bg_loop())
        self.scheduled = {}  # Might change this to a list later.
        self.tasks = []
        self._iter_lock = asyncio.Lock()

    def __unload(self):
        self.bg_loop_task.cancel()
        [task.cancel() for task in self.scheduled.values()]

    # This never should be needed,
    # but it doesn't hurt to add and could cover a weird edge case.
    __del__ = __unload

    async def _load_tasks(self):
        chan_dict = await self.config.all_channels()
        for channel_id, channel_data in chan_dict.items():
            channel = self.bot.get_channel(channel_id)
            if (
                not channel
                or not channel.permissions_for(channel.guild.me).read_messages
            ):
                continue
            tasks_dict = channel_data.get("tasks", {})
            for t in Task.bulk_from_config(**tasks_dict):
                self.tasks.append(t)

    async def bg_loop(self):
        await self.bot.wait_until_ready()
        async with self._iter_lock:
            await self._load_tasks()
        while self == self.bot.get_cog("Scheduler"):
            async with self._iter_lock:
                sleep_for = await self.schedule_upcoming()
            await asyncio.sleep(sleep_for)

    async def delayed_wrap_and_invoke(self, task: Task, delay: int):
        await asyncio.sleep(delay)
        chan = task.channel
        if not chan.permissions_for(chan.guild.me).read_messages:
            return
        message = await task.get_message(self.bot)
        context = await self.bot.get_context(message)
        await self.bot.invoke(context)

    async def schedule_upcoming(self) -> int:
        """
        Schedules some upcoming things as tasks. 
        
        """

        # TODO: improve handlng of next time return
        while not all(task.done() for task in self.scheduled.values()):
            self.log.INFO("Some tasks didn't occur, waiting a moment.")
            await asyncio.sleep(10)

        self.scheduled.clear()

        to_remove = set()

        for task in self.tasks:
            delay = task.next_call_delay
            if delay < 30:
                self.scheduled[task.uid] = asyncio.create_task(
                    self.delayed_wrap_and_invoke(task, delay)
                )
                if not task.recur:
                    to_remove.add(task)

        self.tasks = [t for t in self.tasks if t not in to_remove]

        return 30