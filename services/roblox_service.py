"""
PAG Core
Roblox Service

This module contains the complete Roblox integration layer
for PAG Core.

The service layer is responsible for:

    - Communicating with Roblox APIs
    - Resolving usernames to user IDs
    - Retrieving user profiles
    - Retrieving avatar thumbnails
    - Searching Roblox users
    - Managing HTTP sessions
    - Managing request timeouts
    - Handling rate limits
    - Handling temporary API failures
    - Caching frequently requested data
    - Returning normalized application data

The Discord Cog must not directly communicate with
Roblox APIs.

Architecture:

    Discord Command
            |
            v
        RobloxCog
            |
            v
        RobloxService
            |
            +----------------------+
            |                      |
            v                      v
       Users API             Thumbnails API
            |                      |
            +----------+-----------+
                       |
                       v
                 Normalized Data
                       |
                       v
                  Discord Cog


Supported flow:

    Username
        |
        v
    Resolve User
        |
        v
    Roblox User ID
        |
        +--> User Profile
        |
        +--> Avatar Thumbnail
        |
        +--> Roblox Profile URL
        |
        +--> PAG Account Linking
"""


from __future__ import annotations


import asyncio


import time


from dataclasses import (
    dataclass,
)


from typing import (
    Any,
    Final,
)


import aiohttp


from core.logger import logger


class RobloxServiceError(
    Exception
):
    """
    Base exception for Roblox service errors.
    """


class RobloxUserNotFoundError(
    RobloxServiceError
):
    """
    Raised when a Roblox user cannot be found.
    """


class RobloxRateLimitError(
    RobloxServiceError
):
    """
    Raised when Roblox rate-limits a request.
    """


class RobloxAPIError(
    RobloxServiceError
):
    """
    Raised when Roblox returns an unexpected API error.
    """


class RobloxTimeoutError(
    RobloxServiceError
):
    """
    Raised when a Roblox request times out.
    """


@dataclass(
    slots=True,
)
class RobloxUser:
    """
    Normalized Roblox user representation.

    This object prevents the rest of PAG Core from depending
    directly on Roblox's raw JSON response structure.

    Future systems can safely use:

        user.username

        user.display_name

        user.user_id

        user.avatar_url

        user.profile_url
    """


    user_id: int


    username: str


    display_name: str


    description: str


    created_at: str | None


    is_banned: bool


    avatar_url: str | None = None


    profile_url: str | None = None


    has_verified_badge: bool = False


    @property
    def id(self) -> int:
        """
        Alias for user_id.

        This is useful when other parts of the system
        expect a shorter ID property.
        """

        return self.user_id


    def to_dict(self) -> dict[str, Any]:
        """
        Convert the user object into a dictionary.
        """

        return {

            "user_id": self.user_id,

            "username": self.username,

            "display_name": self.display_name,

            "description": self.description,

            "created_at": self.created_at,

            "is_banned": self.is_banned,

            "avatar_url": self.avatar_url,

            "profile_url": self.profile_url,

            "has_verified_badge": (
                self.has_verified_badge
            ),

        }


class RobloxService:
    """
    Main Roblox API service.

    The service owns a single reusable aiohttp session.

    This is significantly more efficient than creating a new
    HTTP session for every Discord command.

    Lifecycle:

        RobloxService()
            |
            v
        connect()
            |
            v
        API requests
            |
            v
        close()

    The Discord Cog can also use the service without manually
    calling connect() because the service automatically prepares
    the session when needed.
    """


    USERS_BASE_URL: Final[str] = (
        "https://users.roblox.com"
    )


    THUMBNAILS_BASE_URL: Final[str] = (
        "https://thumbnails.roblox.com"
    )


    AVATAR_BASE_URL: Final[str] = (
        "https://avatar.roblox.com"
    )


    REQUEST_TIMEOUT: Final[float] = 15.0


    MAX_RETRIES: Final[int] = 3


    RETRY_DELAY: Final[float] = 1.0


    CACHE_TTL: Final[int] = 300


    MAX_CACHE_SIZE: Final[int] = 512


    def __init__(
        self,
    ) -> None:
        """
        Initialize the Roblox service.
        """

        self._session: aiohttp.ClientSession | None = (
            None
        )


        self._session_lock = asyncio.Lock()


        self._cache: dict[
            str,
            tuple[
                float,
                Any,
            ],
        ] = {}


        self._cache_lock = asyncio.Lock()


        self._closed: bool = False


        self._request_count: int = 0


        self._successful_request_count: int = 0


        self._failed_request_count: int = 0


        logger.info(
            "RobloxService initialized."
        )


    async def _ensure_session(
        self,
    ) -> aiohttp.ClientSession:
        """
        Ensure that a reusable HTTP session exists.

        The lock prevents multiple simultaneous Discord
        commands from creating multiple sessions at once.
        """

        if (
            self._session is not None
            and not self._session.closed
        ):

            return self._session


        async with self._session_lock:

            if (
                self._session is not None
                and not self._session.closed
            ):

                return self._session


            timeout = aiohttp.ClientTimeout(
                total=self.REQUEST_TIMEOUT,
                connect=5,
                sock_read=10,
            )


            headers = {

                "User-Agent": (
                    "PAG-Core/"
                    "Roblox-Integration"
                ),

                "Accept": (
                    "application/json"
                ),

            }


            self._session = (
                aiohttp.ClientSession(
                    timeout=timeout,
                    headers=headers,
                )
            )


            self._closed = False


            logger.info(
                "Roblox HTTP session created."
            )


            return self._session


    async def connect(
        self,
    ) -> None:
        """
        Explicitly initialize the Roblox HTTP session.

        This method can be called during application startup.
        """

        await self._ensure_session()


        logger.info(
            "Roblox service connected."
        )


    async def close(
        self,
    ) -> None:
        """
        Close the HTTP session and clean the service.
        """

        if self._closed:

            return


        self._closed = True


        if self._session is not None:

            try:

                await self._session.close()


            except Exception:

                logger.exception(
                    "Failed to close Roblox HTTP session."
                )


            finally:

                self._session = None


        async with self._cache_lock:

            self._cache.clear()


        logger.info(
            "Roblox service closed."
        )


    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Perform a resilient HTTP request.

        Features:

            - Reusable HTTP session
            - Timeout handling
            - Retry handling
            - Rate-limit handling
            - JSON validation
            - Request statistics
        """

        session = await self._ensure_session()


        last_exception: Exception | None = None


        for attempt in range(
            1,
            self.MAX_RETRIES + 1,
        ):

            self._request_count += 1


            try:

                async with session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                ) as response:

                    if response.status == 200:

                        data = await response.json()


                        self._successful_request_count += 1


                        if not isinstance(
                            data,
                            dict,
                        ):

                            raise RobloxAPIError(
                                "Roblox returned an invalid "
                                "JSON structure."
                            )


                        return data


                    if response.status == 404:

                        raise RobloxUserNotFoundError(
                            "Roblox resource was not found."
                        )


                    if response.status == 429:

                        retry_after = response.headers.get(
                            "Retry-After"
                        )


                        if retry_after:

                            try:

                                delay = float(
                                    retry_after
                                )


                            except ValueError:

                                delay = (
                                    self.RETRY_DELAY
                                    * attempt
                                )


                        else:

                            delay = (
                                self.RETRY_DELAY
                                * attempt
                            )


                        logger.warning(
                            "Roblox rate limit encountered. "
                            "Retrying in %.2f seconds.",
                            delay,
                        )


                        await asyncio.sleep(
                            delay
                        )


                        continue


                    response_text = await response.text()


                    raise RobloxAPIError(
                        (
                            f"Roblox API returned "
                            f"HTTP {response.status}: "
                            f"{response_text[:500]}"
                        )
                    )


            except RobloxUserNotFoundError:

                self._failed_request_count += 1


                raise


            except RobloxAPIError as error:

                last_exception = error


                logger.warning(
                    (
                        "Roblox API error on attempt "
                        "%d/%d: %s"
                    ),
                    attempt,
                    self.MAX_RETRIES,
                    error,
                )


            except asyncio.TimeoutError as error:

                last_exception = error


                logger.warning(
                    (
                        "Roblox request timed out on "
                        "attempt %d/%d."
                    ),
                    attempt,
                    self.MAX_RETRIES,
                )


            except aiohttp.ClientError as error:

                last_exception = error


                logger.warning(
                    (
                        "Roblox network error on "
                        "attempt %d/%d: %s"
                    ),
                    attempt,
                    self.MAX_RETRIES,
                    error,
                )


            if attempt < self.MAX_RETRIES:

                await asyncio.sleep(
                    self.RETRY_DELAY
                    * attempt
                )


        self._failed_request_count += 1


        if isinstance(
            last_exception,
            asyncio.TimeoutError,
        ):

            raise RobloxTimeoutError(
                "Roblox API request timed out."
            )


        raise RobloxAPIError(
            "Roblox API request failed after "
            f"{self.MAX_RETRIES} attempts."
        ) from last_exception


    async def _get_cached(
        self,
        key: str,
    ) -> Any | None:
        """
        Retrieve a value from the in-memory cache.
        """

        async with self._cache_lock:

            cached = self._cache.get(
                key
            )


            if cached is None:

                return None


            created_at, value = cached


            if (
                time.monotonic()
                - created_at
                > self.CACHE_TTL
            ):

                self._cache.pop(
                    key,
                    None,
                )


                return None


            return value


    async def _set_cached(
        self,
        key: str,
        value: Any,
    ) -> None:
        """
        Store a value in the in-memory cache.

        A simple size limit prevents unlimited memory growth.
        """

        async with self._cache_lock:

            if len(
                self._cache
            ) >= self.MAX_CACHE_SIZE:

                oldest_key = min(
                    self._cache,
                    key=lambda item: (
                        self._cache[
                            item
                        ][0]
                    ),
                )


                self._cache.pop(
                    oldest_key,
                    None,
                )


            self._cache[
                key
            ] = (
                time.monotonic(),
                value,
            )


    async def resolve_username(
        self,
        username: str,
    ) -> RobloxUser:
        """
        Resolve a Roblox username into a RobloxUser.

        This uses Roblox's username lookup endpoint.

        The returned object is normalized so that the rest of
        PAG Core does not need to understand the raw API format.
        """

        username = username.strip()


        if not username:

            raise ValueError(
                "Username cannot be empty."
            )


        cache_key = (
            f"user:username:{username.lower()}"
        )


        cached = await self._get_cached(
            cache_key
        )


        if cached is not None:

            return cached


        data = await self._request(
            "POST",
            (
                f"{self.USERS_BASE_URL}"
                "/v1/usernames/users"
            ),
            json={

                "usernames": [
                    username
                ],

                "excludeBannedUsers": False,

            },
        )


        users = data.get(
            "data",
            [],
        )


        if not users:

            raise RobloxUserNotFoundError(
                f"Roblox user not found: {username}"
            )


        user_data = users[0]


        user_id = user_data.get(
            "id"
        )


        actual_username = user_data.get(
            "name",
            username,
        )


        display_name = user_data.get(
            "displayName",
            actual_username,
        )


        if user_id is None:

            raise RobloxAPIError(
                "Roblox returned a user without an ID."
            )


        user = RobloxUser(
            user_id=int(
                user_id
            ),

            username=str(
                actual_username
            ),

            display_name=str(
                display_name
            ),

            description="",

            created_at=None,

            is_banned=False,

        )


        await self._set_cached(
            cache_key,
            user,
        )


        return user


    async def get_user_by_id(
        self,
        user_id: int,
    ) -> RobloxUser:
        """
        Retrieve detailed information about a Roblox user
        using their numeric user ID.
        """

        if user_id <= 0:

            raise ValueError(
                "User ID must be positive."
            )


        cache_key = (
            f"user:id:{user_id}"
        )


        cached = await self._get_cached(
            cache_key
        )


        if cached is not None:

            return cached


        data = await self._request(
            "GET",
            (
                f"{self.USERS_BASE_URL}"
                f"/v1/users/{user_id}"
            ),
        )


        user = RobloxUser(
            user_id=int(
                data.get(
                    "id",
                    user_id,
                )
            ),

            username=str(
                data.get(
                    "name",
                    "Unknown",
                )
            ),

            display_name=str(
                data.get(
                    "displayName",
                    data.get(
                        "name",
                        "Unknown",
                    ),
                )
            ),

            description=str(
                data.get(
                    "description",
                    "",
                )
                or
                ""
            ),

            created_at=data.get(
                "created",
            ),

            is_banned=bool(
                data.get(
                    "isBanned",
                    False,
                )
            ),

        )


        profile_url = (
            "https://www.roblox.com/users/"
            f"{user.user_id}/profile"
        )


        user.profile_url = profile_url


        await self._set_cached(
            cache_key,
            user,
        )


        return user


    async def get_avatar_url(
        self,
        user_id: int,
        *,
        size: str = "420x420",
        format: str = "Png",
        is_circular: bool = False,
    ) -> str | None:
        """
        Retrieve a Roblox avatar thumbnail URL.

        Default:

            420x420 PNG

        This is suitable for:

            - Discord embeds
            - Profile cards
            - Spotlight systems
            - Leaderboards
        """

        if user_id <= 0:

            raise ValueError(
                "User ID must be positive."
            )


        cache_key = (
            "avatar:"
            f"{user_id}:"
            f"{size}:"
            f"{format}:"
            f"{is_circular}"
        )


        cached = await self._get_cached(
            cache_key
        )


        if cached is not None:

            return cached


        data = await self._request(
            "GET",
            (
                f"{self.THUMBNAILS_BASE_URL}"
                "/v1/users/avatar-headshot"
            ),
            params={

                "userIds": str(
                    user_id
                ),

                "size": size,

                "format": format,

                "isCircular": str(
                    is_circular
                ).lower(),

            },
        )


        results = data.get(
            "data",
            [],
        )


        if not results:

            return None


        image_url = results[0].get(
            "imageUrl"
        )


        if image_url:

            await self._set_cached(
                cache_key,
                image_url,
            )


        return image_url


    async def get_user(
        self,
        username: str,
    ) -> RobloxUser | None:
        """
        Retrieve a complete Roblox user object.

        Flow:

            Username
                |
                v
            Resolve username
                |
                v
            User ID
                |
                v
            Detailed profile
                |
                v
            Avatar thumbnail
        """

        try:

            resolved_user = (
                await self.resolve_username(
                    username
                )
            )


        except RobloxUserNotFoundError:

            return None


        user = await self.get_user_by_id(
            resolved_user.user_id
        )


        avatar_url = await self.get_avatar_url(
            user.user_id
        )


        user.avatar_url = avatar_url


        return user


    async def get_profile(
        self,
        username: str,
    ) -> RobloxUser | None:
        """
        Retrieve a complete Roblox profile.

        This method exists as the primary profile-facing
        service method.

        Future profile systems can extend this method with:

            - Group memberships
            - Primary group
            - Badges
            - Presence
            - Avatar configuration
            - Username history
        """

        return await self.get_user(
            username
        )


    async def search_users(
        self,
        keyword: str,
        *,
        limit: int = 10,
    ) -> list[RobloxUser]:
        """
        Search Roblox users by keyword.

        This method is intended for:

            - Autocomplete
            - Admin tools
            - Member linking
            - Search interfaces
        """

        keyword = keyword.strip()


        if not keyword:

            return []


        limit = max(
            1,
            min(
                limit,
                25,
            ),
        )


        cache_key = (
            f"search:{keyword.lower()}:"
            f"{limit}"
        )


        cached = await self._get_cached(
            cache_key
        )


        if cached is not None:

            return cached


        data = await self._request(
            "GET",
            (
                f"{self.USERS_BASE_URL}"
                "/v1/users/search"
            ),
            params={

                "keyword": keyword,

                "limit": limit,

            },
        )


        results = data.get(
            "data",
            [],
        )


        users: list[
            RobloxUser
        ] = []


        for result in results:

            user_id = result.get(
                "id"
            )


            if user_id is None:

                continue


            users.append(
                RobloxUser(

                    user_id=int(
                        user_id
                    ),

                    username=str(
                        result.get(
                            "name",
                            "Unknown",
                        )
                    ),

                    display_name=str(
                        result.get(
                            "displayName",
                            result.get(
                                "name",
                                "Unknown",
                            ),
                        )
                    ),

                    description="",

                    created_at=None,

                    is_banned=False,

                )
            )


        await self._set_cached(
            cache_key,
            users,
        )


        return users


    async def link_account(
        self,
        *,
        discord_id: int,
        roblox_id: int,
        roblox_username: str,
    ) -> dict[str, Any]:
        """
        Prepare a Roblox account link operation.

        The actual database persistence will be added when
        UserRepository is implemented.

        This method is intentionally defined now so that the
        Cog already has a stable service interface.
        """

        if discord_id <= 0:

            raise ValueError(
                "Discord ID must be positive."
            )


        if roblox_id <= 0:

            raise ValueError(
                "Roblox ID must be positive."
            )


        if not roblox_username.strip():

            raise ValueError(
                "Roblox username cannot be empty."
            )


        logger.info(
            (
                "Roblox account link requested: "
                "Discord=%s Roblox=%s"
            ),
            discord_id,
            roblox_id,
        )


        return {

            "discord_id": discord_id,

            "roblox_id": roblox_id,

            "roblox_username": (
                roblox_username
            ),

            "linked": True,

        }


    def get_statistics(
        self,
    ) -> dict[str, Any]:
        """
        Return service statistics.

        Useful for:

            - /status
            - Debugging
            - Monitoring
            - Future dashboard
        """

        return {

            "requests": (
                self._request_count
            ),

            "successful_requests": (
                self._successful_request_count
            ),

            "failed_requests": (
                self._failed_request_count
            ),

            "cache_size": len(
                self._cache
            ),

            "session_active": (
                self._session is not None
                and not self._session.closed
            ),

            "closed": self._closed,

        }