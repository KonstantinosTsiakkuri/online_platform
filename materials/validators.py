import re
from typing import Any
from urllib.parse import urlsplit

from rest_framework import serializers

ALLOWED_DOMAIN = "youtube.com"
URL_PATTERN = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)


def is_allowed_host(url: str) -> bool:
    """Хост должен быть youtube.com или его поддоменом (проверка по hostname, а не подстрокой)."""
    if not url.lower().startswith(("http://", "https://")):
        url = f"http://{url}"
    try:
        hostname = urlsplit(url).hostname
    except ValueError:
        return False
    if not hostname:
        return False
    hostname = hostname.lower().rstrip(".")
    return hostname == ALLOWED_DOMAIN or hostname.endswith(f".{ALLOWED_DOMAIN}")


class YoutubeLinkValidator:
    """Разрешает в текстовом поле только ссылки на youtube.com (и его поддомены).

    Подключается через Meta.validators сериализатора. Пустое значение, текст без ссылок и
    отсутствие поля в attrs (PATCH) проходят проверку.
    """

    requires_context = True

    def __init__(self, field: str) -> None:
        self.field = field

    def __call__(self, attrs: dict[str, Any], serializer: serializers.BaseSerializer[Any]) -> None:
        value = attrs.get(self.field)
        if not value or not isinstance(value, str):
            return
        for match in URL_PATTERN.finditer(value):
            url = match.group(0).rstrip(".,;:!?)")
            if not is_allowed_host(url):
                raise serializers.ValidationError(
                    {
                        self.field: (
                            f'Поле "{self._label(serializer)}" может содержать только ссылки на '
                            f"{ALLOWED_DOMAIN}. Недопустимая ссылка: {url}"
                        )
                    }
                )

    def _label(self, serializer: serializers.BaseSerializer[Any]) -> str:
        model = getattr(getattr(serializer, "Meta", None), "model", None)
        if model is not None:
            try:
                return str(model._meta.get_field(self.field).verbose_name)
            except Exception:  # noqa: BLE001 - запасной вариант: имя поля
                pass
        return self.field

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(field={self.field!r})"
