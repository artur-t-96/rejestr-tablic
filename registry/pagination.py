from django.core.paginator import Paginator

PAGE_SIZE = 50


def list_page(request, queryset):
    # The primary key resolves ties in creation time on every database backend.
    return Paginator(queryset.order_by("-created_at", "-pk"), PAGE_SIZE).get_page(request.GET.get("page"))


def list_context(request, queryset, name):
    page = list_page(request, queryset)
    return {name: page.object_list, "page_obj": page}


def page_url(request, number):
    query = request.GET.copy()
    query["page"] = str(number)
    return request.path + "?" + query.urlencode()
