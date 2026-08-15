import discord
from discord.ext import commands
from typing import List

# ==========================================
# SECURITY BAN SYSTEM
# Sadece Velgrath ve Riwnex kullanabilir
# ==========================================

AUTHORIZED_USER_IDS = {
    1390983947433021561,  # Velgrath ID
    1350724442518716416,  # Riwnex ID
}

class SecurityBan(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def is_authorized(self, user: discord.Member) -> bool:
        if user.id in AUTHORIZED_USER_IDS:
            return True

        if user.guild_permissions.administrator:
            return True

        return False

    async def cog_check(self, ctx: commands.Context):
        if not self.is_authorized(ctx.author):
            await ctx.reply(
                "⛔ Bu güvenlik komutunu kullanamazsın.",
                mention_author=False
            )
            return False
        return True

    @commands.command(name="banid")
    @commands.guild_only()
    async def banid(self, ctx: commands.Context, user_id: int, *, reason: str = "Kalıcı güvenlik banı"):
        try:
            user = await self.bot.fetch_user(user_id)

            try:
                await ctx.guild.fetch_ban(user)
                return await ctx.reply(
                    f"⚠️ **{user}** zaten banlı.",
                    mention_author=False
                )
            except discord.NotFound:
                pass

            await ctx.guild.ban(
                user,
                reason=f"[PAG Security] {reason}",
                delete_message_seconds=0
            )

            embed = discord.Embed(
                title="🔨 Kalıcı ban uygulandı",
                color=discord.Color.red()
            )
            embed.add_field(name="Kullanıcı", value=f"{user} (`{user_id}`)", inline=False)
            embed.add_field(name="Yetkili", value=ctx.author.mention, inline=True)
            embed.add_field(name="Sebep", value=reason, inline=False)

            await ctx.reply(embed=embed, mention_author=False)

        except discord.Forbidden:
            await ctx.reply(
                "❌ Botun ban yetkisi yok veya rol sıralaması yetersiz.",
                mention_author=False
            )

        except discord.HTTPException as e:
            await ctx.reply(
                f"❌ Discord hatası: `{e}`",
                mention_author=False
            )

    @commands.command(name="multiban")
    @commands.guild_only()
    async def multiban(self, ctx: commands.Context, *user_ids: int):
        if len(user_ids) == 0:
            return await ctx.reply(
                "❌ En az bir kullanıcı ID'si girmelisin.",
                mention_author=False
            )

        success = []
        failed = []

        for uid in user_ids[:50]:
            try:
                user = await self.bot.fetch_user(uid)
                await ctx.guild.ban(
                    user,
                    reason="[PAG Security] Toplu güvenlik banı",
                    delete_message_seconds=0
                )
                success.append(str(uid))
            except Exception:
                failed.append(str(uid))

        embed = discord.Embed(
            title="🛡️ Toplu ban tamamlandı",
            color=discord.Color.orange()
        )
        embed.add_field(name="Başarılı", value=str(len(success)), inline=True)
        embed.add_field(name="Başarısız", value=str(len(failed)), inline=True)

        if failed:
            embed.add_field(
                name="Başarısız ID'ler",
                value="`" + "`, `".join(failed[:20]) + "`",
                inline=False
            )

        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="checkban")
    @commands.guild_only()
    async def checkban(self, ctx: commands.Context, user_id: int):
        try:
            user = await self.bot.fetch_user(user_id)
            ban = await ctx.guild.fetch_ban(user)

            await ctx.reply(
                f"✅ **{ban.user}** (`{user_id}`) banlı.",
                mention_author=False
            )

        except discord.NotFound:
            await ctx.reply(
                f"❌ `{user_id}` banlı değil.",
                mention_author=False
            )

    @commands.command(name="unbanid")
    @commands.guild_only()
    async def unbanid(self, ctx: commands.Context, user_id: int):
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user, reason="[PAG Security] Yetkili tarafından kaldırıldı")

            await ctx.reply(
                f"🔓 **{user}** (`{user_id}`) banı kaldırıldı.",
                mention_author=False
            )

        except discord.NotFound:
            await ctx.reply(
                "❌ Kullanıcı banlı değil.",
                mention_author=False
            )

        except discord.Forbidden:
            await ctx.reply(
                "❌ Botun unban yetkisi yok.",
                mention_author=False
            )

    @commands.command(name="banlist")
    @commands.guild_only()
    async def banlist(self, ctx: commands.Context):
        bans = [entry async for entry in ctx.guild.bans(limit=100)]

        if not bans:
            return await ctx.reply(
                "📋 Ban listesi boş.",
                mention_author=False
            )

        lines = []
        for i, entry in enumerate(bans[:20], start=1):
            lines.append(f"**{i}.** {entry.user} (`{entry.user.id}`)")

        embed = discord.Embed(
            title="📋 Ban listesi",
            description="\n".join(lines),
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"Toplam ban: {len(bans)}")

        await ctx.reply(embed=embed, mention_author=False)

async def setup(bot):
    await bot.add_cog(SecurityBan(bot))
