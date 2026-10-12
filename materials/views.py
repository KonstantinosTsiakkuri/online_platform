from rest_framework import generics, viewsets

from .models import Course, Lesson
from .serializers import CourseSerializer, LessonSerializer


class CourseViewSet(viewsets.ModelViewSet[Course]):
    """CRUD для курсов: list, retrieve, create, update, partial_update, destroy."""

    queryset = Course.objects.prefetch_related("lessons")
    serializer_class = CourseSerializer


class LessonListAPIView(generics.ListAPIView[Lesson]):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer


class LessonCreateAPIView(generics.CreateAPIView[Lesson]):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer


class LessonRetrieveAPIView(generics.RetrieveAPIView[Lesson]):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer


class LessonUpdateAPIView(generics.UpdateAPIView[Lesson]):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer


class LessonDestroyAPIView(generics.DestroyAPIView[Lesson]):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer
