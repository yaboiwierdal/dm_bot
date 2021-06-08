import sqlite3
import datetime
import asyncio
import os

import discord
from discord.ext import commands

TOKEN = os.environ["TOKEN"]
GUILD = os.environ["GUILD"]

bot = commands.Bot(
    command_prefix=">",
    activity=discord.Activity(type=discord.ActivityType.listening, name=">help"),
)


connection = sqlite3.connect("dm_bot.db")


cursor = connection.cursor()


@bot.event
async def on_ready():
    for guild in bot.guilds:
        if guild.name == GUILD:
            break

    print(
        f"{bot.user} is connected to the following guild:\n"
        f"name: {guild.name}, id: {guild.id}"
    )


bot.remove_command("help")


class Help(commands.MinimalHelpCommand):
    async def send_pages(self):
        destination = self.get_destination()
        for page in self.paginator.pages:
            embed = discord.Embed(description=page)
            await destination.send(embed=embed)


bot.help_command = Help(command_attrs={"hidden": True})


class List_Commands(commands.Cog):
    def __init(self, bot):
        self.bot = bot

    @commands.command()
    async def list_commands(self, ctx):
        """See a list of commands for the user."""
        member = ctx.author

        commands_string = await list_user_commands(ctx)

        embed = discord.Embed(
            title=f"{member.display_name}'s Commands",
            description=f"{commands_string}",
            color=0x000000,
        )

        await ctx.send(embed=embed)


async def list_user_commands(ctx):
    member = ctx.author
    user = member.id

    commands_list = cursor.execute(
        """SELECT command FROM user_commands WHERE discord_user = (?) AND enabled = (?)""",
        (user, 1),
    ).fetchall()

    commands_string = " "

    for item in commands_list:
        commands_string += item[0] + "\n"

    if commands_string == " ":
        commands_string = "You don't have any commands set."

    return commands_string


class DM_Settings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def dm_add(self, ctx, *, command):
        """Add command to monitor"""
        user = ctx.author
        user = user.id

        find_command = cursor.execute(
            """SELECT command, enabled FROM user_commands WHERE command = (?) AND discord_user = (?)""",
            (command, user),
        ).fetchone()

        if find_command is not None:
            # check enabled value
            if find_command[1] == 1:
                return await ctx.send("You already have that command enabled.")

            return await toggle_on(ctx, user, command)

        return await add_command(ctx, user, command)

    @commands.command()
    async def dm_remove(self, ctx, *, command):
        """Remove monitored command"""
        user = ctx.author
        user = user.id

        find_command = cursor.execute(
            f"""SELECT command, enabled FROM user_commands WHERE command = (?) AND discord_user = (?)""",
            (command, user),
        ).fetchone()

        if find_command is not None:
            if find_command[1] == 0:
                return await ctx.send("You already have that command toggled off.")

            return await toggle_off(ctx, user, command)

        return await ctx.send("That command is not toggled on.")


async def add_command(ctx, user, command):
    cursor.execute(
        f"""INSERT INTO user_commands (discord_user, command, enabled) VALUES (?, ?, ?)""",
        (user, command, 1),
    )
    connection.commit()

    return await ctx.send(f"You will now be notified everytime you use `{command}`.")


async def toggle_on(ctx, user, command):
    cursor.execute(
        """ UPDATE user_commands SET enabled = (?) WHERE discord_user = (?) AND command = (?)""",
        (1, user, command),
    )
    connection.commit()

    return await ctx.send(f"Notifications for `{command}` toggled on.")


async def toggle_off(ctx, user, command):
    cursor.execute(
        """ UPDATE user_commands SET enabled = (?) WHERE discord_user = (?) AND command = (?)""",
        (0, user, command),
    )
    connection.commit()

    return await ctx.send(f"Notifications for `{command}` toggled off.")


class CommandErrorHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        cog = ctx.cog
        if cog:
            if cog._get_overridden_method(cog.cog_command_error) is not None:
                return

        ignored = (commands.CommandNotFound,)
        error = getattr(error, "original", error)

        if isinstance(error, ignored):
            return


def setup(bot):
    bot.add_cog(List_Commands(bot))
    bot.add_cog(DM_Settings(bot))
    bot.add_cog(CommandErrorHandler(bot))


setup(bot)


@bot.listen("on_message")
async def message_listener(message):
    if message.author.bot is False:
        next_message = await wait_for_func(message)

        command, is_command = await is_user_command(message)

        await asyncio.sleep(0.5)

        if is_command is True and next_message is not None:
            if next_message.embeds:
                if any([e.type == "rich" for e in next_message.embeds]):
                    embed = await dm_if_embed(message, command)
                    return await message.author.send(embed=embed)

                embed = await dm_if_link(message, command, next_message)
                return await message.author.send(embed=embed)

            embed = await dm_if_not_embed(message, command, next_message)
            return await message.author.send(embed=embed)


async def wait_for_func(message):
    channel = message.channel

    def check_for_bot_message(m):
        return m.author.bot and m.channel == channel

    def check_for_user_message(m):
        return not m.author.bot and m.channel == channel

    done, pending = await asyncio.wait(
        [
            bot.wait_for("message", check=check_for_bot_message),
            bot.wait_for("message", check=check_for_user_message),
        ],
        return_when=asyncio.FIRST_COMPLETED,
    )

    next_message = done.pop().result()

    for future in done:
        future.exception()

    for future in pending:
        future.cancel()

    if next_message.author.bot is True:
        return next_message

    return None


async def is_user_command(message):
    user = message.author
    user = user.id
    message_start = message.content.split(" ")[0]

    user_commands = cursor.execute(
        """SELECT command FROM user_commands WHERE discord_user = (?) AND enabled = (?)""",
        (user, 1),
    ).fetchall()

    for command in user_commands:
        if message_start == command[0]:
            return command, True

    return " ", False


async def dm_if_embed(message, command):
    guild = message.guild
    link = message.jump_url

    value = "The bot sent an embed."
    embed = await create_alert_embed(command, guild, message, value, link)

    return embed


async def dm_if_link(message, command, bot_message):
    guild = message.guild
    link = message.jump_url
    link_name = bot_message.content[0:80] + "..."
    value = f"[{link_name}]({bot_message.content})"

    embed = await create_alert_embed(command, guild, message, value, link)

    return embed


async def dm_if_not_embed(message, command, bot_message):
    guild = message.guild
    link = message.jump_url
    this_message = bot_message.content

    if len(this_message) > 80:
        this_message = this_message[0:80] + "..."

    value = f"{this_message}"

    embed = await create_alert_embed(command, guild, message, value, link)

    return embed


async def create_alert_embed(command, guild, message, value, link):
    embed = discord.Embed(
        title="Command Alert",
        description=f"You just used `{command[0]}` in {guild.name}",
        color=0x000000,
    )
    embed.set_thumbnail(
        url="https://raw.githubusercontent.com/yaboiwierdal/dm_bot/main/images/circle-cropped(4).png"
    )
    embed.add_field(name="Message", value=f"{message.content}", inline=False)
    embed.add_field(name="Bot's Reply", value=f"{value}", inline=False)
    embed.add_field(
        name="Conversation", value=f"[Jump to message!]({link})", inline=False
    )
    embed.timestamp = datetime.datetime.utcnow()

    return embed


bot.run(TOKEN)
