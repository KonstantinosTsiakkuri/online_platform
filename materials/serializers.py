from rest_framework import serializers

from .models import Course, Lesson


class CourseSerializer(serializers.ModelSerializer[Course]):
    class Meta:
        model = Course
        fields = "__all__"


class LessonSerializer(serializers.ModelSerializer[Lesson]):
    class Meta:
        model = Lesson
        fields = "__all__"
