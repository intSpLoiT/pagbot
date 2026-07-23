from __future__ import annotations

from collections.abc import Iterable

import discord

from utils.errors import PAGPermissionError


class PAGPermissions:
    """
    PAG Bot ortak yetki kontrolleri.
    """

    # =========================================================
    # DISCORD PERMISSIONS
    # =========================================================

    @staticmethod
    def has_permission(
        member: discord.Member,
        permission: str,
    ) -> bool:
        """
        Kullanıcının Discord yetkisini kontrol eder.

        Örnek:
            PAGPermissions.has_permission(
                member,
                "manage_messages",
            )
        """

        permissions = member.guild_permissions

        if not hasattr(permissions, permission):
            raise ValueError(
                f"Unknown Discord permission: {permission}"
            )

        return bool(
            getattr(permissions, permission)
        )

    # =========================================================
    # ADMIN
    # =========================================================

    @staticmethod
    def is_administrator(
        member: discord.Member,
    ) -> bool:
        """
        Administrator yetkisini kontrol eder.
        """

        return member.guild_permissions.administrator

    # =========================================================
    # ROLE CHECK
    # =========================================================

    @staticmethod
    def has_role(
        member: discord.Member,
        role_id: int,
    ) -> bool:
        """
        Kullanıcının belirli bir role sahip olup olmadığını
        kontrol eder.
        """

        return any(
            role.id == role_id
            for role in member.roles
        )

    # =========================================================
    # MULTIPLE ROLES
    # =========================================================

    @staticmethod
    def has_any_role(
        member: discord.Member,
        role_ids: Iterable[int],
    ) -> bool:
        """
        Kullanıcının belirtilen rollerden en az birine
        sahip olup olmadığını kontrol eder.
        """

        role_ids = set(role_ids)

        return any(
            role.id in role_ids
            for role in member.roles
        )

    # =========================================================
    # REQUIRE PERMISSION
    # =========================================================

    @staticmethod
    def require_permission(
        member: discord.Member,
        permission: str,
    ) -> None:
        """
        Yetki yoksa PAGPermissionError fırlatır.
        """

        if not PAGPermissions.has_permission(
            member,
            permission,
        ):
            raise PAGPermissionError(
                f"Missing required permission: {permission}"
            )

    # =========================================================
    # REQUIRE ROLE
    # =========================================================

    @staticmethod
    def require_role(
        member: discord.Member,
        role_id: int,
    ) -> None:
        """
        Kullanıcı gerekli role sahip değilse
        PAGPermissionError fırlatır.
        """

        if not PAGPermissions.has_role(
            member,
            role_id,
        ):
            raise PAGPermissionError(
                "You do not have the required role."
            )

    # =========================================================
    # REQUIRE ADMIN
    # =========================================================

    @staticmethod
    def require_administrator(
        member: discord.Member,
    ) -> None:
        """
        Kullanıcının administrator olup olmadığını kontrol eder.
        """

        if not PAGPermissions.is_administrator(
            member,
        ):
            raise PAGPermissionError(
                "Administrator permission is required."
            )