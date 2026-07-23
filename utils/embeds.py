from __future__ import annotations

from typing import Any

import discord


class PAGEmbeds:
    """
    PAG Bot için ortak Discord Embed yardımcıları.

    Tüm sistemlerde aynı görsel yapıyı kullanmak için
    merkezi embed üretimi sağlar.
    """

    FOOTER_TEXT = "PAG Bot"

    # =========================================================
    # BASE
    # =========================================================

    @staticmethod
    def base(
        title: str,
        description: str | None = None,
        *,
        color: discord.Colour | None = None,
    ) -> discord.Embed:
        """
        Temel PAG embed'i oluşturur.
        """

        embed = discord.Embed(
            title=title,
            description=description,
            color=color or discord.Colour.blurple(),
        )

        embed.set_footer(
            text=PAGEmbeds.FOOTER_TEXT,
        )

        return embed

    # =========================================================
    # SUCCESS
    # =========================================================

    @staticmethod
    def success(
        title: str,
        description: str | None = None,
    ) -> discord.Embed:
        """
        Başarılı işlemler için embed.
        """

        return PAGEmbeds.base(
            title=f"✅ {title}",
            description=description,
            color=discord.Colour.green(),
        )

    # =========================================================
    # ERROR
    # =========================================================

    @staticmethod
    def error(
        title: str,
        description: str | None = None,
    ) -> discord.Embed:
        """
        Hatalar için embed.
        """

        return PAGEmbeds.base(
            title=f"❌ {title}",
            description=description,
            color=discord.Colour.red(),
        )

    # =========================================================
    # WARNING
    # =========================================================

    @staticmethod
    def warning(
        title: str,
        description: str | None = None,
    ) -> discord.Embed:
        """
        Uyarılar için embed.
        """

        return PAGEmbeds.base(
            title=f"⚠️ {title}",
            description=description,
            color=discord.Colour.orange(),
        )

    # =========================================================
    # INFO
    # =========================================================

    @staticmethod
    def info(
        title: str,
        description: str | None = None,
    ) -> discord.Embed:
        """
        Bilgilendirme mesajları için embed.
        """

        return PAGEmbeds.base(
            title=f"ℹ️ {title}",
            description=description,
            color=discord.Colour.blue(),
        )

    # =========================================================
    # CUSTOM
    # =========================================================

    @staticmethod
    def custom(
        title: str,
        description: str | None = None,
        *,
        color: discord.Colour | None = None,
        fields: list[dict[str, Any]] | None = None,
        thumbnail_url: str | None = None,
        image_url: str | None = None,
    ) -> discord.Embed:
        """
        Özel ihtiyaçlar için esnek embed oluşturur.
        """

        embed = PAGEmbeds.base(
            title=title,
            description=description,
            color=color,
        )

        if fields:
            for field in fields:
                embed.add_field(
                    name=str(field["name"]),
                    value=str(field["value"]),
                    inline=field.get("inline", False),
                )

        if thumbnail_url:
            embed.set_thumbnail(
                url=thumbnail_url,
            )

        if image_url:
            embed.set_image(
                url=image_url,
            )

        return embed