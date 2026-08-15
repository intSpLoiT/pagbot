import discord
from discord.ext import commands

OWNER_USERNAME = "velgrath_"

class BanID(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="banid")
    async def banid(self, ctx, user_id: int, *, reason: str = "Tekrar banlandı"):
        # Sadece velgrath_ kullanabilsin
        if ctx.author.name.lower() != OWNER_USERNAME:
            return

        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.ban(user, reason=reason)
            await ctx.reply(
                f"🔨 **{user}** (`{user_id}`) tekrar banlandı.\\nSebep: {reason}",
                mention_author=False
            )
        except discord.Forbidden:
            await ctx.reply(
                "❌ Botun ban yetkisi yok veya kullanıcının rolü daha yüksek.",
                mention_author=False
            )
        except discord.HTTPException as e:
            await ctx.reply(
                f"❌ Ban işlemi başarısız: `{e}`",
                mention_author=False
            )

async def setup(bot):
    await bot.add_cog(BanID(bot))
