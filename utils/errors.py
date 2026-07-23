from __future__ import annotations


class PAGError(Exception):
    """
    PAG Bot'a ait tüm özel hataların temel sınıfı.
    """

    def __init__(
        self,
        message: str = "An unexpected PAG Bot error occurred.",
    ) -> None:
        super().__init__(message)


class DatabaseError(PAGError):
    """
    Database işlemleri sırasında oluşan hatalar.
    """

    def __init__(
        self,
        message: str = "A database error occurred.",
    ) -> None:
        super().__init__(message)


class ConfigurationError(PAGError):
    """
    Configuration veya environment ayarlarıyla ilgili hatalar.
    """

    def __init__(
        self,
        message: str = "A configuration error occurred.",
    ) -> None:
        super().__init__(message)


class PAGPermissionError(PAGError):
    """
    PAG Bot içindeki yetki kontrollerinde oluşan hatalar.
    """

    def __init__(
        self,
        message: str = "You do not have permission to perform this action.",
    ) -> None:
        super().__init__(message)


class ValidationError(PAGError):
    """
    Kullanıcı veya sistem verileri geçersiz olduğunda kullanılır.
    """

    def __init__(
        self,
        message: str = "The provided data is invalid.",
    ) -> None:
        super().__init__(message)