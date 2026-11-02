from rest_framework.pagination import PageNumberPagination


class MaterialsPagination(PageNumberPagination):
    """Пагинация списков курсов и уроков: ?page=N&page_size=M (максимум 50)."""

    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 50
