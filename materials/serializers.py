from typing import Any

from rest_framework import serializers

from .models import Course, Lesson
from .validators import YoutubeLinkValidator


class LessonSerializer(serializers.ModelSerializer[Lesson]):
    class Meta:
        model = Lesson
        fields = "__all__"
        read_only_fields = ("owner",)
        validators = [
            YoutubeLinkValidator(field="title"),
            YoutubeLinkValidator(field="description"),
            YoutubeLinkValidator(field="video_url"),
        ]


class CourseSerializer(serializers.ModelSerializer[Course]):
    lessons_count = serializers.SerializerMethodField()
    lessons = LessonSerializer(many=True, read_only=True)
    is_subscribed = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = "__all__"
        read_only_fields = ("owner",)
        validators = [
            YoutubeLinkValidator(field="title"),
            YoutubeLinkValidator(field="description"),
        ]

    def get_lessons_count(self, obj: Course) -> int:
        return obj.lessons.count()

    def get_is_subscribed(self, obj: Course) -> bool:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        return bool(obj.subscriptions.filter(user=user).exists())


class SubscriptionRequestSerializer(serializers.Serializer[Any]):
    """Тело запроса подписки (используется для документации)."""

    course_id = serializers.IntegerField(min_value=1, help_text="ID курса")
