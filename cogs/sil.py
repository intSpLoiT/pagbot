import asyncio
import discord
from discord.ext import commands

OWNER_USERNAME = "velgrath_"

class DMCleanup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="cleanupdm")
    async def cleanup_dm(self, ctx, limit: int = 500):
        # Sadece velgrath_ kullanabilsin
        if ctx.author.name.lower() != OWNER_USERNAME:
            return

        await ctx.reply(
            "🧹 Botun DM mesajları temizleniyor...",
            mention_author=False
        )

        deleted = 0
        scanned = 0
        skipped = 0
        failed = 0

        for channel in list(self.bot.private_channels):
            if not isinstance(channel, discord.DMChannel):
                continue

            scanned += 1
            recipient = getattr(channel, "recipient", None)

            # Velgrath ile olan DM kanalına ASLA dokunma
            if recipient and recipient.name.lower() == OWNER_USERNAME:
                skipped += 1
                continue

            try:
                async for message in channel.history(limit=limit):
                    # Sadece botun kendi mesajlarını sil
                    if message.author.id != self.bot.user.id:
                        continue

                    try:
                        await message.delete()
                        deleted += 1
                        await asyncio.sleep(0.3)

                    except discord.NotFound:
                        continue
                    except discord.Forbidden:
                        break
                    except discord.HTTPException:
                        await asyncio.sleep(1)

            except (discord.Forbidden, discord.HTTPException):
                failed += 1

        await ctx.send(
            (
                f"✅ Temizlik tamamlandı.\\n"
                f"Silinen bot mesajı: {deleted}\\n"
                f"Taranan DM: {scanned}\\n"
                f"Korunan DM (Velgrath): {skipped}\\n"
                f"Hata alınan DM: {failed}"
            ),
            delete_after=15
        )

async def setup(bot):
    await bot.add_cog(DMCleanup(bot))
